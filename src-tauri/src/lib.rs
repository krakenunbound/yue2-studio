//! YuE2 Studio host: owns and supervises the local Python sidecar.

use std::ffi::OsStr;
use std::io::{BufRead, BufReader};
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
        .invoke_handler(tauri::generate_handler![sidecar_url, sidecar_ws_url, sidecar_http, sidecar_error, open_outputs_folder])
        .build(tauri::generate_context!())
        .expect("error while building YuE2 Studio")
        .run(move |_app, event| {
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                exit_shutdown.store(true, Ordering::SeqCst);
                if let Some(mut child) = exit_sidecar.lock().unwrap().take() {
                    kill_process_tree(child.id());
                    let _ = child.wait();
                }
            }
        });
}
