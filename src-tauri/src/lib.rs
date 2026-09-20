//! YuE2 Studio host: owns and supervises the local Python sidecar.

use std::ffi::OsStr;
use std::io::{BufRead, BufReader};
#[cfg(test)]
use std::io::Read;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Emitter, Manager, RunEvent, State};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

const SIDECAR_HOST: &str = "127.0.0.1";
const SIDECAR_PORT: u16 = 7794;
const INSTANCE_LOCK_PORT: u16 = 7795;
const SIDECAR_PROTOCOL: u64 = 3;
const WATCHDOG_POLL: Duration = Duration::from_secs(2);
const SIDECAR_DOWN_GRACE: Duration = Duration::from_secs(6);
const SIDECAR_BOOT_TIMEOUT: Duration = Duration::from_secs(20);

struct InstanceLock {
    _listener: Option<TcpListener>,
}
fn take_instance_lock() -> Option<TcpListener> {
    let listener = TcpListener::bind((SIDECAR_HOST, INSTANCE_LOCK_PORT)).ok()?;
    let _ = listener.set_nonblocking(true);
    Some(listener)
}

fn project_root() -> PathBuf {
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    // Installed copies must use their own payload even when launched from a
    // terminal or shortcut whose working directory is another studio checkout.
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            if parent.join("python").join("main.py").is_file() {
                return parent.to_path_buf();
            }
        }
    }
    let mut candidates = vec![cwd.clone()];
    if let Some(parent) = cwd.parent().filter(|_| cwd.ends_with("src-tauri")) {
        candidates.push(parent.to_path_buf());
    }
    if let Ok(exe) = std::env::current_exe() {
        candidates.extend(exe.ancestors().skip(1).take(7).map(PathBuf::from));
    }
    candidates
        .into_iter()
        .find(|path| path.join("python").join("main.py").is_file())
        .unwrap_or(cwd)
}

fn hidden_command<S: AsRef<OsStr>>(program: S) -> Command {
    let mut command = Command::new(program);
    #[cfg(target_os = "windows")]
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

fn venv_python() -> PathBuf {
    let root = project_root();
    let bundled = root.join("python").join("standalone").join("python.exe");
    if bundled.is_file() { bundled } else {
        root.join("python").join("venv").join("Scripts").join("python.exe")
    }
}

fn sidecar_entry() -> PathBuf { project_root().join("python").join("main.py") }

fn already_listening() -> bool {
    std::net::TcpStream::connect_timeout(
        &format!("{SIDECAR_HOST}:{SIDECAR_PORT}").parse().unwrap(),
        Duration::from_millis(150),
    ).is_ok()
}

fn sidecar_healthy() -> bool {
    let url = format!("http://{SIDECAR_HOST}:{SIDECAR_PORT}/health");
    let response = match ureq::get(&url).timeout(Duration::from_millis(900)).call() {
        Ok(response) => response,
        Err(_) => return false,
    };
    let body = match response.into_string() {
        Ok(body) => body,
        Err(_) => return false,
    };
    let payload: serde_json::Value = match serde_json::from_str(&body) {
        Ok(payload) => payload,
        Err(_) => return false,
    };
    payload.get("ok").and_then(serde_json::Value::as_bool) == Some(true)
        && payload.get("service").and_then(serde_json::Value::as_str) == Some("YuE2 Studio")
        && payload.get("protocol").and_then(serde_json::Value::as_u64) == Some(SIDECAR_PROTOCOL)
}

fn abort_remote_writing() {
    use std::io::{Read, Write};
    use std::net::{SocketAddr, TcpStream};
    let address = SocketAddr::from(([127, 0, 0, 1], SIDECAR_PORT));
    if let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(400)) {
        let _ = stream.set_write_timeout(Some(Duration::from_millis(400)));
        let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
        let request = b"POST /api/assist/abort HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
        let _ = stream.write_all(request);
        let mut sink = [0u8; 256];
        let _ = stream.read(&mut sink);
    }
}

fn kill_process_tree(pid: u32) {
    #[cfg(target_os = "windows")]
    { let _ = hidden_command("taskkill").args(["/PID", &pid.to_string(), "/T", "/F"]).stdout(Stdio::null()).stderr(Stdio::null()).status(); }
    #[cfg(not(target_os = "windows"))]
    { let _ = Command::new("kill").args(["-TERM", &pid.to_string()]).status(); }
}

fn terminate_existing_sidecars() {
    let entry = sidecar_entry().display().to_string();
    #[cfg(target_os = "windows")]
    {
        let escaped = entry.replace('\'', "''");
        let script = format!(
            "$entry = '{}'; $self = $PID; Get-CimInstance Win32_Process | Where-Object {{ $_.ProcessId -ne $self -and $_.Name -match '^python(w)?\\.exe$' -and $_.CommandLine -and $_.CommandLine.Contains($entry) }} | ForEach-Object {{ taskkill /PID $_.ProcessId /T /F | Out-Null }}",
            escaped
        );
        let _ = hidden_command("powershell").args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &script]).stdout(Stdio::null()).stderr(Stdio::null()).status();
    }
}

fn wait_for_port_free(timeout: Duration) -> bool {
    let deadline = std::time::Instant::now() + timeout;
    while std::time::Instant::now() < deadline {
        if !already_listening() { return true; }
        thread::sleep(Duration::from_millis(250));
    }
    !already_listening()
}

fn spawn_sidecar() -> Result<Child, String> {
    let python = venv_python();
    let entry = sidecar_entry();
    if !python.is_file() { return Err(format!("sidecar Python missing at {}", python.display())); }
    let mut command = hidden_command(&python);
    let tools = project_root().join("tools");
    if tools.join("ffmpeg.exe").is_file() {
        let mut paths = vec![tools];
        if let Some(existing) = std::env::var_os("PATH") {
            paths.extend(std::env::split_paths(&existing));
        }
        if let Ok(path) = std::env::join_paths(paths) { command.env("PATH", path); }
    }
    let mut child = command.arg(&entry)
        .current_dir(project_root().join("python"))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("sidecar spawn failed: {error}"))?;
    if let Some(out) = child.stdout.take() {
        thread::spawn(move || for line in BufReader::new(out).lines().map_while(Result::ok) { eprintln!("[yue2] {line}"); });
    }
    if let Some(err) = child.stderr.take() {
        thread::spawn(move || for line in BufReader::new(err).lines().map_while(Result::ok) { eprintln!("[yue2] {line}"); });
    }
    Ok(child)
}

fn wait_for_sidecar() -> bool {
    let deadline = Instant::now() + SIDECAR_BOOT_TIMEOUT;
    while Instant::now() < deadline {
        if sidecar_healthy() { return true; }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

fn start_owned_sidecar(slot: &Arc<Mutex<Option<Child>>>, error_slot: &Arc<Mutex<Option<String>>>) -> Result<(), String> {
    let child = spawn_sidecar()?;
    *slot.lock().unwrap() = Some(child);
    if wait_for_sidecar() {
        *error_slot.lock().unwrap() = None;
        return Ok(());
    }
    let error = "The local YuE2 service did not become ready within 20 seconds.".to_string();
    *error_slot.lock().unwrap() = Some(error.clone());
    Err(error)
}

#[tauri::command]
fn sidecar_url() -> String { format!("http://{SIDECAR_HOST}:{SIDECAR_PORT}") }

#[derive(serde::Serialize)]
struct SidecarHttpResult {
    status: u16,
    body: String,
}

#[derive(serde::Serialize)]
struct EffectAudioChoice {
    path: String,
    name: String,
    size: u64,
}

const MAX_EFFECT_AUDIO_BYTES: u64 = 512 * 1024 * 1024;

fn validate_effect_audio_file(file_path: &str) -> Result<(PathBuf, u64, String), String> {
    let path = PathBuf::from(file_path);
    let metadata = std::fs::metadata(&path)
        .map_err(|error| format!("Could not read the selected sound file ({error})"))?;
    if !metadata.is_file() {
        return Err("Choose an audio file, not a folder or device.".into());
    }
    let size = metadata.len();
    if size == 0 {
        return Err("The selected sound file is empty.".into());
    }
    if size > MAX_EFFECT_AUDIO_BYTES {
        return Err("The selected sound file is larger than the 512 MiB import limit.".into());
    }
    let extension = path.extension().and_then(OsStr::to_str)
        .map(str::to_ascii_lowercase)
        .filter(|value| matches!(value.as_str(), "wav" | "mp3" | "flac" | "m4a" | "aac" | "ogg" | "opus" | "webm"))
        .ok_or_else(|| "Choose a WAV, MP3, FLAC, M4A, AAC, OGG, Opus, or WebM sound file.".to_string())?;
    Ok((path, size, extension))
}

fn effect_audio_choice_from_path(path: PathBuf) -> Result<EffectAudioChoice, String> {
    let path_text = path.display().to_string();
    let (_, size, _) = validate_effect_audio_file(&path_text)?;
    let name = path
        .file_name()
        .and_then(OsStr::to_str)
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("Imported sound")
        .to_string();
    Ok(EffectAudioChoice {
        path: path_text,
        name,
        size,
    })
}

fn import_effect_audio_to_url(file_path: String, name: String, endpoint: &str) -> Result<SidecarHttpResult, String> {
    let (path, size, _) = validate_effect_audio_file(&file_path)?;
    let filename = path.file_name().and_then(OsStr::to_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "The selected sound file needs a file name.".to_string())?;
    let file = std::fs::File::open(&path)
        .map_err(|error| format!("Could not open the selected sound file ({error})"))?;
    let request = ureq::post(endpoint)
        .query("filename", filename)
        .query("name", name.trim())
        .set("Content-Type", "application/octet-stream")
        .set("Content-Length", &size.to_string())
        .timeout(SIDECAR_TIMEOUT);
    match request.send(file) {
        Ok(ok) => Ok(SidecarHttpResult { status: ok.status(), body: ok.into_string().unwrap_or_default() }),
        Err(ureq::Error::Status(status, error)) => Ok(SidecarHttpResult { status, body: error.into_string().unwrap_or_default() }),
        Err(error) => Err(format!("The local YuE2 service at {endpoint} did not answer ({error})")),
    }
}

#[tauri::command]
async fn choose_effect_audio() -> Result<Option<EffectAudioChoice>, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let selected = rfd::FileDialog::new()
            .add_filter("Audio files", &["wav", "mp3", "flac", "m4a", "aac", "ogg", "opus", "webm"])
            .pick_file();
        match selected {
            None => Ok(None),
            Some(path) => effect_audio_choice_from_path(path).map(Some),
        }
    })
    .await
    .map_err(|error| format!("The file chooser thread failed ({error})"))?
}

#[tauri::command]
async fn import_effect_audio(file_path: String, name: String) -> Result<SidecarHttpResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        import_effect_audio_to_url(
            file_path,
            name,
            &format!("http://{SIDECAR_HOST}:{SIDECAR_PORT}/api/effects/import"),
        )
    })
    .await
    .map_err(|error| format!("The sound import thread failed ({error})"))?
}

/// How long the host will wait on the sidecar before giving up.
///
/// Cloud writing calls are the slow ones; the backend already caps itself at 90s
/// per model call, so this only has to be comfortably above that.
const SIDECAR_TIMEOUT: Duration = Duration::from_secs(180);

#[tauri::command]
async fn sidecar_http(method: String, path: String, body: Option<String>, content_type: Option<String>) -> Result<SidecarHttpResult, String> {
    // WebView2 blocks some window.fetch calls from https://tauri.localhost to
    // 127.0.0.1 (POST preflight / private-network). Call the sidecar from the
    // host process instead so Create song does not depend on that fetch.
    //
    // This MUST stay `async` and do its blocking work on a worker thread. As a
    // plain `fn`, Tauri runs the command on the main thread, so ureq pinned the
    // UI thread for the whole request and the window could not process a single
    // event until it returned. That was invisible while every call was
    // sub-second, and became a hard multi-second freeze once cloud writing
    // calls went through the same path.
    if !path.starts_with('/') || path.starts_with("//") {
        return Err("Invalid sidecar path".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let url = format!("http://{SIDECAR_HOST}:{SIDECAR_PORT}{path}");
        let mut request = ureq::request(method.as_str(), &url)
            .timeout(SIDECAR_TIMEOUT);
        if let Some(content_type) = content_type.as_deref().filter(|value| !value.is_empty()) {
            request = request.set("Content-Type", content_type);
        }
        let response = match body {
            Some(payload) => request.send_string(&payload),
            None => request.call(),
        };
        match response {
            Ok(ok) => Ok(SidecarHttpResult { status: ok.status(), body: ok.into_string().unwrap_or_default() }),
            Err(ureq::Error::Status(status, err)) => Ok(SidecarHttpResult { status, body: err.into_string().unwrap_or_default() }),
            Err(error) => Err(format!("The local YuE2 service at {url} did not answer ({error})")),
        }
    })
    .await
    .map_err(|error| format!("The sidecar request thread failed ({error})"))?
}

#[tauri::command]
fn sidecar_ws_url() -> String { format!("ws://{SIDECAR_HOST}:{SIDECAR_PORT}") }

#[tauri::command]
fn sidecar_error(state: State<'_, Arc<Mutex<Option<String>>>>) -> Option<String> {
    state.lock().ok().and_then(|value| value.clone())
}

#[tauri::command]
fn open_outputs_folder() -> Result<String, String> {
    let path = project_root().join("outputs").join("library");
    std::fs::create_dir_all(&path).map_err(|error| error.to_string())?;
    #[cfg(target_os = "windows")]
    hidden_command("explorer").arg(&path).spawn().map_err(|error| error.to_string())?;
    Ok(path.display().to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let sidecar_error_state: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(None));
    let shutting_down = Arc::new(AtomicBool::new(false));
    let setup_sidecar = sidecar.clone();
    let setup_error = sidecar_error_state.clone();
    let watch_sidecar = sidecar.clone();
    let watch_error = sidecar_error_state.clone();
    let exit_sidecar = sidecar.clone();
    let watch_shutdown = shutting_down.clone();
    let exit_shutdown = shutting_down.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(sidecar_error_state)
        .setup(move |app| {
            let handle = app.handle().clone();
            // Only one Studio window may own the sidecar. Extra windows were
            // respawning python and emitting "The local service restarted"
            // in the middle of Create song.
            let instance_lock = take_instance_lock();
            let owns_sidecar = instance_lock.is_some();
            app.manage(InstanceLock { _listener: instance_lock });
            if owns_sidecar {
                // Owning the instance lock means no live Studio window owns a
                // server. Never adopt a listener left behind by an older build:
                // its request schema may not match this UI, and because there is
                // no Child handle it would survive this app closing as well.
                terminate_existing_sidecars();
                if !wait_for_port_free(Duration::from_secs(8)) {
                    let error = format!("Port {SIDECAR_PORT} is occupied by another application.");
                    *setup_error.lock().unwrap() = Some(error.clone());
                    let _ = handle.emit("sidecar-error", error);
                } else if let Err(error) = start_owned_sidecar(&setup_sidecar, &setup_error) {
                    let _ = handle.emit("sidecar-error", error);
                }
                thread::spawn(move || {
                    loop {
                        thread::sleep(WATCHDOG_POLL);
                        if watch_shutdown.load(Ordering::SeqCst) { break; }
                        // A loaded YuE2 worker can spend minutes inside GPU
                        // inference without servicing a health request promptly.
                        // The desktop owns this exact Child, so process liveness
                        // is the authoritative watchdog signal. Restarting merely
                        // because HTTP timed out used to kill healthy generations
                        // just before they could be saved.
                        let child_running = {
                            let mut guard = watch_sidecar.lock().unwrap();
                            match guard.as_mut() {
                                Some(child) => match child.try_wait() {
                                    Ok(None) => true,
                                    Ok(Some(_)) | Err(_) => {
                                        *guard = None;
                                        false
                                    }
                                },
                                None => false,
                            }
                        };
                        if child_running { continue; }
                        if !wait_for_port_free(SIDECAR_DOWN_GRACE) {
                            let error = format!("The YuE2 service stopped, but port {SIDECAR_PORT} is still occupied.");
                            *watch_error.lock().unwrap() = Some(error.clone());
                            let _ = handle.emit("sidecar-error", error);
                            continue;
                        }
                        match start_owned_sidecar(&watch_sidecar, &watch_error) {
                            Ok(()) => {
                                let _ = handle.emit("sidecar-restarted", ());
                            }
                            Err(error) => {
                                // start_owned_sidecar may still hold a process
                                // that failed its boot check. Retire it before a
                                // later watchdog attempt so retries cannot pile up.
                                if let Some(mut child) = watch_sidecar.lock().unwrap().take() {
                                    kill_process_tree(child.id());
                                    let _ = child.wait();
                                }
                                *watch_error.lock().unwrap() = Some(error.clone());
                                let _ = handle.emit("sidecar-error", error);
                            }
                        }
                    }
                });
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![sidecar_url, sidecar_ws_url, sidecar_http, choose_effect_audio, import_effect_audio, sidecar_error, open_outputs_folder])
        .build(tauri::generate_context!())
        .expect("error while building YuE2 Studio")
        .run(move |_app, event| {
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                exit_shutdown.store(true, Ordering::SeqCst);
                abort_remote_writing();
                if let Some(mut child) = exit_sidecar.lock().unwrap().take() {
                    kill_process_tree(child.id());
                    let _ = child.wait();
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::sync::mpsc;

    #[test]
    fn import_streams_binary_bytes_and_encodes_unicode_name() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let (request_tx, request_rx) = mpsc::channel();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut header_bytes = Vec::new();
            let mut byte = [0u8; 1];
            while stream.read_exact(&mut byte).is_ok() {
                header_bytes.push(byte[0]);
                if header_bytes.ends_with(b"\r\n\r\n") { break; }
            }
            let headers = String::from_utf8(header_bytes).unwrap();
            let content_length = headers.lines()
                .find_map(|line| line.strip_prefix("Content-Length: "))
                .unwrap().parse::<usize>().unwrap();
            let mut body = vec![0u8; content_length];
            stream.read_exact(&mut body).unwrap();
            request_tx.send((headers, body)).unwrap();
            stream.write_all(b"HTTP/1.1 201 Created\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK").unwrap();
        });

        let path = std::env::temp_dir().join(format!("yue2-effect-upload-{}-cafe.wav", std::process::id()));
        let expected = vec![0, 1, 2, 255, 0, 128, 42];
        std::fs::write(&path, &expected).unwrap();
        let result = import_effect_audio_to_url(
            path.display().to_string(),
            "Café rain".to_string(),
            &format!("http://{address}/api/effects/import"),
        ).unwrap();
        let (headers, body) = request_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        server.join().unwrap();
        std::fs::remove_file(path).unwrap();

        assert_eq!(result.status, 201);
        assert_eq!(result.body, "OK");
        assert!(headers.starts_with("POST /api/effects/import?filename=yue2-effect-upload-"));
        assert!(headers.contains("name=Caf%C3%A9+rain"));
        assert_eq!(body, expected);
    }

    #[test]
    fn effect_import_rejects_missing_and_empty_files() {
        let missing = std::env::temp_dir().join(format!("yue2-no-effect-{}-missing.wav", std::process::id()));
        assert!(validate_effect_audio_file(&missing.display().to_string()).is_err());

        let empty = std::env::temp_dir().join(format!("yue2-no-effect-{}-empty.wav", std::process::id()));
        std::fs::write(&empty, []).unwrap();
        assert_eq!(
            validate_effect_audio_file(&empty.display().to_string()).unwrap_err(),
            "The selected sound file is empty."
        );
        std::fs::remove_file(empty).unwrap();
    }

    #[test]
    fn picked_effect_keeps_the_complete_source_filename() {
        let path = std::env::temp_dir().join(format!(
            "yue2-effect-choice-{}-foo.bar.wav",
            std::process::id()
        ));
        std::fs::write(&path, [1u8]).unwrap();
        let choice = effect_audio_choice_from_path(path.clone()).unwrap();
        std::fs::remove_file(path).unwrap();

        assert_eq!(choice.name, format!("yue2-effect-choice-{}-foo.bar.wav", std::process::id()));
        assert_eq!(choice.size, 1);
    }
}
