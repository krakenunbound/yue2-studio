from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yue2_engine
import cover_art


class YuE2StudioContractTests(unittest.TestCase):
    def test_lan_access_is_optional_and_browser_uses_page_origin(self):
        root = Path(__file__).resolve().parents[2]
        api = (root / "src" / "api.ts").read_text(encoding="utf-8")
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        main = (root / "python" / "main.py").read_text(encoding="utf-8")
        self.assertIn("window.location.origin", api)
        self.assertIn('credentials: "include"', api)
        self.assertIn("LAN ACCESS", app)
        self.assertIn("Start LAN sharing", app)
        self.assertNotIn("LAN password", app)
        self.assertIn('host="0.0.0.0"', main)
        self.assertIn("LAN_PORT", main)
        self.assertIn("serve_lan", main)
        self.assertIn("lan_access.gate", main)
        self.assertIn("StaticFiles", main)
        self.assertIn("LAN_PORT = 6969", (root / "python" / "config.py").read_text(encoding="utf-8"))

    def test_keys_drawer_has_lan_ollama_server_fields(self):
        keys = (Path(__file__).resolve().parents[2] / "src" / "KeysDrawer.tsx").read_text(encoding="utf-8")
        vault = (Path(__file__).resolve().parents[1] / "ai_vault.py").read_text(encoding="utf-8")
        self.assertIn("Local LLM", keys)
        self.assertNotIn("LAN server", keys)
        self.assertNotIn("Save and use LAN Ollama", keys)
        self.assertNotIn("Enable LAN writing", keys)
        self.assertIn("Server URL", keys)
        self.assertIn("Enable Local LLM writing", keys)
        self.assertIn("gemma3:4b", keys)
        self.assertIn("isLocalLlm", keys)
        self.assertIn('"ollama"', vault)
        self.assertIn("base_url", vault)

    def test_character_picker_only_shows_voices_for_the_open_slot(self):
        panel = (Path(__file__).resolve().parents[2] / "src" / "VoiceProfilesPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("profilesForSlot(shown, pickerSlot)", panel)
        self.assertNotIn("disabled={!allowed}", panel)

    def test_easy_mode_shows_writing_source_not_generic_cloud(self):
        app = (Path(__file__).resolve().parents[2] / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("writingSource", app)
        self.assertIn("Local LLM ·", app)
        self.assertNotIn("cloud model — the GPU is still idle", app)
        self.assertIn("turn.brief", app)
        self.assertIn("|| content", app)

    def test_new_playlist_from_song_menu_keeps_that_song(self):
        app = (Path(__file__).resolve().parents[2] / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("setCollectionSeedSong(song)", app)
        create = app.split("async function saveCollection", 1)[1].split("async function addToPlaylist", 1)[0]
        self.assertIn("collectionSeedSong", create)
        self.assertIn("addSongToPlaylist(playlist.id, song.id)", create)

    def test_radio_station_is_a_top_mode_with_eq(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        radio = (root / "src" / "RadioPage.tsx").read_text(encoding="utf-8")
        profiles = (root / "src" / "eqProfiles.ts").read_text(encoding="utf-8")
        self.assertIn(">Radio<", app)
        self.assertIn('studioView === "radio"', app)
        self.assertIn("RadioPage", app)
        self.assertIn("function radioSrc", radio)
        self.assertIn("function startTrack", radio)
        self.assertIn("toggleLibraryPlay", app)
        self.assertIn("EQ_BANDS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]", profiles)
        self.assertIn("Shuffle", radio)
        self.assertIn("Repeat", radio)

    def test_radio_visualizer_uses_live_frequency_bars(self):
        radio = (Path(__file__).resolve().parents[2] / "src" / "RadioPage.tsx").read_text(encoding="utf-8")
        self.assertIn("createMediaElementSource", radio)
        self.assertIn("createAnalyser", radio)
        self.assertIn("getByteFrequencyData", radio)
        self.assertIn("fftSize = 256", radio)
        self.assertNotIn("Math.sin(t *", radio)
        self.assertIn("pendingPlayId", radio)
        self.assertIn("if (current?.id !== song.id)", radio)

    def test_radio_exposes_library_curator_actions(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        radio = (root / "src" / "RadioPage.tsx").read_text(encoding="utf-8")
        self.assertIn("onAddToPlaylist={addToPlaylist}", app)
        self.assertIn("onNewPlaylistForSong={newPlaylistForSong}", app)
        self.assertIn("onEditSong={editSong}", app)
        self.assertIn("onGenerateCover={prepareGenerateCover}", app)
        self.assertIn("onDeleteSong={prepareDeleteSong}", app)
        for action in ("New playlist", "Edit details / rename", "Generate cover art", "Delete song"):
            self.assertIn(action, radio)

    def test_radio_supports_optional_automatic_eq_profiles(self):
        root = Path(__file__).resolve().parents[2]
        radio = (root / "src" / "RadioPage.tsx").read_text(encoding="utf-8")
        profiles = (root / "src" / "eqProfiles.ts").read_text(encoding="utf-8")
        hook = (root / "src" / "useAutoEq.ts").read_text(encoding="utf-8")
        panel = (root / "src" / "EqPanel.tsx").read_text(encoding="utf-8")
        css = (Path(__file__).resolve().parents[2] / "src" / "App.css").read_text(encoding="utf-8")
        self.assertIn("function automaticPreset", profiles)
        self.assertIn('localStorage.getItem(AUTO_EQ_STORAGE)', hook)
        self.assertIn('checked={autoEq}', panel)
        self.assertIn("Auto EQ", panel)
        self.assertIn("radio-auto-eq", css)
        self.assertIn("setAutoEq(false)", hook)
        self.assertIn("requestAnimationFrame(animate)", hook)
        self.assertIn("sliders glide on track changes", radio)
        self.assertIn('className={autoEq && autoPreset === name ? "auto-active"', panel)
        self.assertIn('const genre = (song.genre || "").toLowerCase()', profiles)

    def test_orbitwave_background_tracks_library_with_toggle(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        galaxy = (root / "src" / "OrbitGalaxy.tsx").read_text(encoding="utf-8")
        css = (root / "src" / "App.css").read_text(encoding="utf-8")
        self.assertIn("OrbitGalaxy", app)
        self.assertIn("galaxyEnabled", app)
        self.assertIn("yue2-orbitwave-enabled", app)
        self.assertIn("aria-pressed={galaxyEnabled}", app)
        self.assertIn('studioView === "live" && <OrbitGalaxy', app)
        self.assertIn('studioView === "live" && <button type="button" className={`galaxy-toggle', app)
        self.assertIn("song.title", galaxy)
        self.assertIn("new THREE.WebGLRenderer", galaxy)
        self.assertIn("new THREE.ShaderMaterial", galaxy)
        self.assertIn("STAR_COUNT = 4200", galaxy)
        self.assertIn("RIBBON_FONT_SIZE = 125", galaxy)
        self.assertIn("RING_GAP = 0.92", galaxy)
        self.assertIn("RING_WIDTH = 0.7", galaxy)
        self.assertIn("OrbitControls", galaxy)
        self.assertIn("autoRotate = true", galaxy)
        self.assertIn("autoRotateSpeed = 0.25", galaxy)
        self.assertIn("retintRings", galaxy)
        self.assertIn("syncCatalog", galaxy)
        self.assertIn("[catalogKey]", galaxy)
        self.assertIn("orbitalGroup.rotation.x +=", galaxy)
        self.assertIn("orbitalGroup.rotation.z +=", galaxy)
        self.assertNotIn("VIEW_PHI", galaxy)
        self.assertNotIn("guidePositions", galaxy)
        self.assertIn("starfield.rotation.y +=", galaxy)
        self.assertIn("fog: false", galaxy)
        self.assertIn("nativeCapacity", galaxy)
        self.assertIn("isRecent", galaxy)
        self.assertIn("CURRENT_COLOR", galaxy)
        self.assertIn("RECENT_COLOR", galaxy)
        self.assertIn("analyser", galaxy)
        self.assertIn("onAnalyserChange", (root / "src" / "LivePage.tsx").read_text(encoding="utf-8"))
        self.assertIn("requestAnimationFrame(render)", galaxy)
        self.assertIn(".orbit-galaxy", css)

    def test_live_random_station_uses_templates_and_vocal_coin_flip(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        live = (root / "src" / "LivePage.tsx").read_text(encoding="utf-8")
        extras = (root / "src" / "extraPresets.ts").read_text(encoding="utf-8")
        self.assertIn(">Live<", app)
        self.assertIn('studioView === "live"', app)
        self.assertIn("LivePage", app)
        self.assertIn("EXTRA_STYLE_PRESETS", app)
        self.assertIn("randomPick", live)
        self.assertIn("randomCast", live)
        self.assertIn("writeSong", live)
        self.assertIn("result.title", live)
        self.assertIn("<h3>{current.title}</h3>", live)
        self.assertIn("voice_slots", live)
        self.assertNotIn("veto", live.lower())
        self.assertIn("DEFAULT_BUFFER_SIZE = 5", live)
        self.assertIn("MIN_BUFFER_SIZE = 3", live)
        self.assertIn("queued to be made", live)
        self.assertNotIn("synchronizeLyrics", live)
        self.assertIn("randomCatalogIds", live)
        self.assertIn("catalogBuffer", live)
        self.assertNotIn("selectedCatalogIds", live)
        self.assertNotIn("BUFFER SOURCES", live)
        self.assertNotIn("live-pending", live)
        self.assertIn("SongVisualizer", live)
        self.assertIn("live-reels", live)
        self.assertIn("CAST_ROLL", live)
        self.assertNotIn("Random station", live)
        self.assertIn("startupTarget", live)
        self.assertIn("if (missing > 0)", live)
        self.assertIn("else if (!activePick && pending.length === 0)", live)
        self.assertIn("generatedIds", live)
        self.assertIn("PLAYBACK QUEUE", live)
        self.assertIn("!on && <div className=\"live-settings card\">", live)
        self.assertIn("queue.slice(index)", live)
        self.assertIn("useAutoEq", live)
        self.assertIn("eqGains={displayGains}", live)
        self.assertIn('className="live-eq"', live)
        self.assertIn('"current on-air"', live)
        live_css = (root / "src" / "LivePage.css").read_text(encoding="utf-8")
        self.assertIn(".live-queue-row.on-air", live_css)
        self.assertIn("getCurrentWindow", app)
        self.assertIn('event.key !== "F11"', app)
        self.assertIn("setFullscreen", app)
        self.assertIn("setDecorations", app)
        capabilities = (root / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8")
        self.assertIn('"core:window:allow-set-fullscreen"', capabilities)
        self.assertIn('"core:window:allow-set-decorations"', capabilities)
        self.assertIn("event.repeat", app)
        self.assertIn("Atlanta trap", extras)
        self.assertIn("Brooklyn drill", extras)
        self.assertIn("Corridos", extras)
        self.assertIn("Cafe bossa nova", extras)
        self.assertIn("80s hair band", extras)
        self.assertIn("80s techno", extras)
        app_art = app.split("const TEMPLATE_ART", 1)[1].split("const STYLE_PRESETS", 1)[0]
        self.assertIn("EXTRA_TEMPLATE_ART", app_art)
        thumbs = list((root / "src" / "assets" / "templates").glob("*.webp"))
        names = [
            "atlanta-trap", "brooklyn-drill", "east-coast-boom-bap", "pop-rap", "latin-pop",
            "corridos", "reggae", "soul-rnb", "gospel", "cafe-bossa", "contemporary-folk",
            "heroic-trailer", "fantasy-adventure", "bedtime-lullaby", "cute-character",
            "80s-hair-band", "80s-techno",
        ]
        have = {path.stem for path in thumbs}
        missing = [name for name in names if name not in have]
        self.assertEqual(missing, [], msg=f"missing template thumbnails: {missing}")

    def test_finished_jobs_freeze_elapsed_time(self):
        app = (Path(__file__).resolve().parents[2] / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (Path(__file__).resolve().parents[2] / "src" / "App.css").read_text(encoding="utf-8")
        elapsed = app.split("function elapsedLabel", 1)[1].split("function remainingLabel", 1)[0]
        self.assertIn("finished_at", elapsed)
        self.assertIn('generationJob?.status !== "succeeded"', app)
        self.assertIn("toggleLibraryPlay", app)
        self.assertIn(".job-banner.succeeded span", css)

    def test_instrumental_generation_uses_multi_section_conditioning(self):
        lyrics = yue2_engine._lyrics_for_generation({"instrumental": True})
        sections = [line for line in lyrics.splitlines() if line.startswith("[")]
        content = [line for line in lyrics.splitlines() if line == "(instrumental)"]

        self.assertGreaterEqual(len(sections), 5)
        self.assertEqual(len(sections), len(content))
        self.assertIn("[Intro]", sections)
        self.assertIn("[Instrumental]", sections)
        self.assertIn("[Outro]", sections)
        self.assertNotIn("[Verse]", sections)
        self.assertNotIn("[Chorus]", sections)

    def test_vocal_generation_keeps_rendered_lyrics(self):
        self.assertEqual(
            "[Verse]\nWords",
            yue2_engine._lyrics_for_generation({
                "instrumental": False,
                "lyrics": "original",
                "rendered_lyrics": "[Verse]\nWords",
            }),
        )

    def test_worker_progress_survives_tqdm_prefix(self):
        line = 'sampling: 42% YUE2_PROGRESS {"progress": 0.42}'
        self.assertEqual('{"progress": 0.42}', yue2_engine._event(line, "YUE2_PROGRESS"))

    def test_bare_worker_progress_marker_is_ignored(self):
        self.assertIsNone(yue2_engine._event("YUE2_PROGRESS", "YUE2_PROGRESS"))

    def test_payload_free_done_signal_is_handled_separately(self):
        source = Path(yue2_engine.__file__).read_text(encoding="utf-8")
        self.assertIn('line.strip() == "YUE2_DONE"', source)
        self.assertNotIn('_event(line, "YUE2_DONE")', source)

    def test_cancel_can_terminate_worker_during_startup(self):
        released = threading.Event()

        class Stream:
            def readline(self):
                released.wait(2)
                return ""

        class Process:
            pid = 12345
            stdout = Stream()
            stdin = None
            stopped = False
            def poll(self): return 1 if self.stopped else None
            def wait(self, timeout=None): self.stopped = True; return 1
            def kill(self): self.stopped = True; released.set()

        process = Process()
        failures = []
        def start():
            try: yue2_engine._start(threading.Event())
            except RuntimeError as error: failures.append(str(error))
        def taskkill(*_args, **_kwargs):
            process.stopped = True; released.set()
            return type("Result", (), {"returncode": 0})()

        with patch.object(yue2_engine, "WORKER_PYTHON", Path(__file__)), patch.object(yue2_engine.subprocess, "Popen", return_value=process), patch.object(yue2_engine.subprocess, "run", side_effect=taskkill):
            thread = threading.Thread(target=start)
            thread.start()
            deadline = time.monotonic() + 1
            while yue2_engine._PROCESS is not process and time.monotonic() < deadline:
                time.sleep(0.01)
            started = time.monotonic()
            yue2_engine.cancel()
            self.assertLess(time.monotonic() - started, 1.0)
            thread.join(2)
        yue2_engine._PROCESS = None
        self.assertFalse(thread.is_alive())

    def test_worker_receives_top_k_variation_control(self):
        root = Path(__file__).resolve().parents[1]
        worker = (root / "yue2_worker.py").read_text(encoding="utf-8")
        engine = (root / "yue2_engine.py").read_text(encoding="utf-8")
        self.assertIn('"top_k": int(request.get("top_k", 100))', engine)
        self.assertIn('"temperature": float(request.get("temperature", 1.0))', engine)
        self.assertIn('"abc": request.get("abc_score") or None', engine)
        self.assertIn("select_ar_backend", worker)
        self.assertIn("from yue2_speed import", worker)

    def test_cover_renderer_has_anatomy_guard_and_step_progress(self):
        root = Path(__file__).resolve().parents[1]
        renderer = (root / "cover_art_renderer.py").read_text(encoding="utf-8")
        bridge = (root / "cover_art.py").read_text(encoding="utf-8")
        self.assertIn("extra limbs", renderer)
        self.assertIn("COVER_PROGRESS", renderer)
        self.assertIn("progress_base + progress_span", bridge)

    def test_stem_runner_uses_parseable_progress_and_local_model(self):
        root = Path(__file__).resolve().parents[1]
        runner = (root / "demucs_runner.py").read_text(encoding="utf-8")
        studio = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn("STEM_PROGRESS", runner)
        self.assertIn('STEMS_ROOT', studio)
        self.assertIn('"--repo", str(STEMS_ROOT)', studio)

    def test_library_player_uses_blob_analyser_bars(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        visualizer = (root / "src" / "SongVisualizer.tsx").read_text(encoding="utf-8")
        self.assertIn("createObjectURL", visualizer)
        self.assertIn("createMediaElementSource", visualizer)
        self.assertIn("getByteFrequencyData", visualizer)
        self.assertIn("fftSize = 1024", visualizer)
        self.assertIn("EQ_BANDS", visualizer)
        self.assertIn("createBiquadFilter", visualizer)
        self.assertNotIn("captureStream", visualizer)
        self.assertNotIn("Math.sin(t *", visualizer)
        self.assertIn("Stop and return to 0:00", visualizer)
        self.assertIn("element.currentTime = 0", visualizer)
        self.assertIn("SongVisualizer", app)

    def test_song_studio_uses_existing_stems_instead_of_an_audiomass_iframe(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        studio = (root / "src" / "SongStudio.tsx").read_text(encoding="utf-8")
        self.assertIn("<SongStudio", app)
        self.assertIn('extractStems(songFolderName(song), "4")', app)
        self.assertIn("studioStemJob", app)
        self.assertNotIn('<iframe title={`Audio Editor', app)
        for feature in ("Original mix", "Mute", "solo", "Export custom mix", "Instrumental", "Acapella"):
            self.assertIn(feature.casefold(), studio.casefold())

    def test_studio_spectrum_stays_in_app_without_popup(self):
        studio = (Path(__file__).resolve().parents[2] / "src" / "SongStudio.tsx").read_text(encoding="utf-8")
        self.assertIn("function Spectrum", studio)
        self.assertIn("captureStream", studio)
        self.assertIn("stream.getAudioTracks().length === 0", studio)
        self.assertIn('audio.addEventListener("playing", connect)', studio)
        self.assertNotIn("window.open", studio)

    def test_studio_failure_is_contained_instead_of_blanking_the_application(self):
        studio = (Path(__file__).resolve().parents[2] / "src" / "SongStudio.tsx").read_text(encoding="utf-8")
        self.assertIn("class StudioCrashBoundary", studio)
        self.assertIn("static getDerivedStateFromError", studio)
        self.assertIn("Studio could not open", studio)
        self.assertIn("<StudioCrashBoundary", studio)

    def test_studio_exposes_local_multitrack_editing_without_a_track_cap(self):
        root = Path(__file__).resolve().parents[2]
        studio = (root / "src" / "SongStudio.tsx").read_text(encoding="utf-8")
        api = (root / "src" / "api.ts").read_text(encoding="utf-8")
        backend = (root / "python" / "main.py").read_text(encoding="utf-8")
        for feature in ("Add track", "Fade in", "Fade out", "Trim song", "Mute range", "Export range", "Undo", "Redo", "This Lane", "All lanes", "Echo", "Reverb", "Auto-pan", "Low-pass", "High-pass", "Telephone", "Saturation", "Tremolo", "Stereo widen", "Limiter", "Auto level", "Normalize", "Louder", "Quieter", "Razor", "Insert space", "EFFECTS & SOUNDS", "From your library", "Start of song", "Start of clip or range", "L/R split", "studio-ruler"):
            self.assertIn(feature, studio)
        self.assertIn("offset: position", studio)
        self.assertIn('max={Math.max(.01, mixEnd)}', studio)
        self.assertIn("const silenceAudio", studio)
        self.assertIn("peak * gain", studio)
        self.assertIn('gain={clipGain(clip)}', studio)
        self.assertIn("blockTop: bounds.top", studio)
        self.assertIn("key={activeEditorSong.id}", (root / "src" / "App.tsx").read_text(encoding="utf-8"))
        effects_page = (root / "src" / "EffectsPage.tsx").read_text(encoding="utf-8")
        self.assertIn("Open Studio", effects_page)
        self.assertIn("importStudioTrack", api)
        self.assertIn("studio/import", backend)
        self.assertIn("tracks: list[StudioTrackState] = Field(default_factory=list)", backend)
        self.assertNotIn("tracks: list[StudioTrackState] = Field(default_factory=list, max_length", backend)

    def test_library_cards_reserve_full_left_edge_for_larger_art(self):
        css = (Path(__file__).resolve().parents[2] / "src" / "App.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:132px minmax(0,1fr) 42px", css)
        self.assertIn("grid-row:1/3", css)
        self.assertIn("grid-column:2/4", css)

    def test_library_stem_branch_exposes_stems_and_moves_them_to_studio(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (root / "src" / "App.css").read_text(encoding="utf-8")
        self.assertIn('title="Stems"', app)
        self.assertIn('className="stem-tree-icon"', app)
        self.assertIn("Move stems to Studio", app)
        self.assertIn("void openAudioEditor(song)", app)
        self.assertIn(".stem-branch-panel{", css)

    def test_karaoke_player_uses_continuous_timing_and_one_lyric_layer(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        lyrics = (root / "src" / "KaraokeLyrics.tsx").read_text(encoding="utf-8")
        visualizer = (root / "src" / "SongVisualizer.tsx").read_text(encoding="utf-8")
        css = (root / "src" / "App.css").read_text(encoding="utf-8")
        self.assertIn("function KaraokeLyrics", lyrics)
        self.assertIn("requestAnimationFrame", visualizer)
        self.assertIn('className="karaoke-track"', lyrics)
        self.assertIn('className="karaoke-translation"', lyrics)
        self.assertIn("const focusOffset = compact ? 21 : 104", lyrics)
        self.assertEqual(1, css.count(".karaoke-track{"))

    def test_karaoke_panel_has_a_persistent_collapse_toggle(self):
        visualizer = (Path(__file__).resolve().parents[2] / "src" / "SongVisualizer.tsx").read_text(encoding="utf-8")
        self.assertIn('className={`transport-lyrics', visualizer)
        self.assertIn('localStorage.setItem("yue2-lyrics-visible"', visualizer)
        self.assertIn('lyricsVisible && <KaraokeLyrics', visualizer)
        self.assertIn('aria-pressed={lyricsVisible && hasTimedLyrics}', visualizer)

    def test_easy_templates_wait_for_send_and_default_jpop_to_japanese(self):
        app = (Path(__file__).resolve().parents[2] / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("function inferLyricsLanguage", app)
        self.assertIn("function startFromTemplate", app)
        self.assertNotIn("void sendChat(`${name}. ${preset.genre}. ${preset.mood}`", app)
        self.assertIn('language: "ja"', app)
        self.assertIn("Add last-minute notes, then send", app)
        self.assertIn("setEasyTemplate(name)", app)
        self.assertIn("setChatInput(`${name}. ${preset.genre}. ${preset.mood}.${languageLine}`)", app)
        self.assertNotIn("if (extra.includes(name)) return extra", app)
        self.assertIn("More templates", app)
        self.assertNotIn("View all ${Object.keys(STYLE_PRESETS).length}", app)
        self.assertIn("cancelEasyCreate", app)
        self.assertIn("translateLyricsToEnglish", app)
        self.assertIn("Translate to English", app)
        self.assertIn("setSendNudge", app)
        self.assertIn("scrollIntoView", app)

    def test_karaoke_does_not_highlight_upcoming_lines_during_instrumental_gaps(self):
        lyrics = (Path(__file__).resolve().parents[2] / "src" / "KaraokeLyrics.tsx").read_text(encoding="utf-8")
        self.assertIn("const performingIndex = lines.findIndex", lyrics)
        self.assertIn("let focusIndex = performingIndex", lyrics)
        self.assertIn('index === performingIndex ? "active"', lyrics)
        self.assertNotIn('index === activeIndex ? "active"', lyrics)

    def test_lyrics_sync_is_local_and_optional(self):
        root = Path(__file__).resolve().parents[2]
        setup = (root / "Setup Lyrics Sync.bat").read_text(encoding="utf-8")
        bridge = (root / "python" / "lyrics_sync.py").read_text(encoding="utf-8")
        generate = (root / "python" / "main.py").read_text(encoding="utf-8")
        self.assertIn("lyrics_sync.run(job, song_dir, metadata)", generate)
        self.assertIn('"needs_lyric_sync"', generate)
        self.assertIn('not request.get("instrumental")', generate)
        self.assertIn("yue2_engine.cancel()", generate)
        self.assertIn('"timed_lyrics": lyrics_sync.load(song_dir)', generate)
        worker = (root / "python" / "lyrics_align_worker.py").read_text(encoding="utf-8")
        self.assertIn("def force_align_known_lyrics", worker)
        self.assertIn("start_seconds", worker)
        live = (root / "src" / "LivePage.tsx").read_text(encoding="utf-8")
        self.assertIn("await generate({", live)
        self.assertNotIn("synchronizeLyrics", live)
        self.assertIn("whisperx==3.8.4", setup)
        self.assertIn("torchcodec==0.7.0", setup)
        manager = (root / "python" / "model_manager.py").read_text(encoding="utf-8")
        self.assertIn("torchcodec==0.7.0", manager)
        self.assertIn("RUNTIME_PACKAGE_PINS", manager)
        self.assertIn("importlib.metadata", manager)
        self.assertIn('ROOT / "models" / "lyrics"', bridge)
        self.assertIn("WORKER_TIMEOUT_SECONDS", bridge)
        self.assertIn("timed out on GPU, retrying on CPU", bridge)
        self.assertIn("os._exit(0)", worker)
        self.assertIn("result_event = event", bridge)
        self.assertIn("break", bridge)
        self.assertIn('"HF_HOME"', bridge)
        self.assertIn('"PYTHONIOENCODING": "utf-8"', bridge)
        self.assertNotIn("http://127.0.0.1", bridge)

    def test_prompt_presets_wrap_without_an_overlapping_scrollbar(self):
        css = (Path(__file__).resolve().parents[2] / "src" / "App.css").read_text(encoding="utf-8")
        helper_rule = css.split(".helper-presets{", 1)[1].split("}", 1)[0]
        self.assertIn("flex-wrap:wrap", helper_rule)
        self.assertIn("overflow:visible", helper_rule)
        self.assertNotIn("overflow-x:auto", helper_rule)

    def test_memory_button_color_reflects_loaded_state(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (root / "src" / "App.css").read_text(encoding="utf-8")
        self.assertIn('status?.service.worker_loaded ? "memory-loaded" : "memory-empty"', app)
        self.assertIn(".memory-loaded{border-color:#ff5470", css)
        self.assertIn(".memory-empty,.memory-empty:disabled{border-color:#54e0a0", css)

    def test_cover_model_has_one_canonical_local_path(self):
        self.assertEqual("juggernaut_aftermath.safetensors", cover_art.MODEL.name)
        self.assertEqual("cover_art", cover_art.MODEL.parent.name)
        self.assertEqual("models", cover_art.MODEL.parent.parent.name)
        self.assertNotIn("Kraken_Audio", str(cover_art.MODEL))

    def test_yue2_model_contract_has_main_model_tokenizer_and_vae(self):
        self.assertEqual(set(yue2_engine.MODEL_FILES), {"model", "config", "tokenizer", "vae", "vae_config"})
        self.assertTrue(str(yue2_engine.MODEL_FILES["model"]).endswith("model.safetensors"))
        self.assertTrue(str(yue2_engine.MODEL_FILES["tokenizer"]).endswith("qwen.tiktoken"))

    def test_yue2_model_status_requires_each_component(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = {
                "model": root / "model.safetensors", "config": root / "config.json",
                "tokenizer": root / "qwen.tiktoken", "vae": root / "vae.safetensors", "vae_config": root / "vae.json",
            }
            paths["model"].write_bytes(b"d")
            with patch.dict(yue2_engine.MODEL_FILES, paths, clear=True):
                status = yue2_engine.model_status()
            self.assertFalse(status["ready"])
            self.assertEqual(status["present"], 1)
            self.assertEqual(status["missing"], ["config", "tokenizer", "vae", "vae_config"])

    def test_runtime_is_explicitly_standalone(self):
        self.assertIs(yue2_engine.runtime_status()["standalone"], True)

    def test_frontend_accepts_official_caption_headings_and_keeps_jobs_separate(self):
        app = (Path(__file__).resolve().parents[2] / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("function isStructuredCaption", app)
        self.assertIn("#{1,6}", app)
        self.assertIn("const [generationJob", app)
        self.assertIn("const [utilityJob", app)
        self.assertIn("create-job-banner", app)
        self.assertNotIn("const [job, setJob]", app)

    def test_yue2_controls_and_complete_reuse_settings_are_wired(self):
        app = (Path(__file__).resolve().parents[2] / "src" / "App.tsx").read_text(encoding="utf-8")
        for control in ("cot_mode: cotMode", "abc_score: abcScore.trim() || undefined", "cfg, steps, top_k: topK, temperature"):
            self.assertIn(control, app)
        for setting in ("setLockedSeed", "setCotMode", "setAbcScore", "setCfg", "setSteps", "setTopK", "setTemperature", "setExcludeStyles", "setVocalGender"):
            self.assertIn(setting, app)
        self.assertNotIn("tiled_decode", app)
        self.assertNotIn("auto_duration", app)

    def test_reuse_as_new_song_requests_a_random_seed(self):
        app = (Path(__file__).resolve().parents[2] / "src" / "App.tsx").read_text(encoding="utf-8")
        reuse = app.split("function reuseSong", 1)[1].split("async function saveSongDetails", 1)[0]
        self.assertIn('setLockedSeed("")', reuse)
        self.assertNotIn("setLockedSeed(String(song.seed))", reuse)

    def test_remix_menu_has_obvious_choices_and_limitation_tooltip(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        form = (root / "src" / "createForm.ts").read_text(encoding="utf-8")
        css = (root / "src" / "App.css").read_text(encoding="utf-8")
        main = (root / "python" / "main.py").read_text(encoding="utf-8")
        self.assertIn("Remix this song", app)
        self.assertIn("Keep the melody", app)
        self.assertIn("Keep melody and chords", app)
        self.assertIn("openRemix(song)", app)
        self.assertIn("cot_mode: remixMode", app)
        self.assertIn("seed: null", app.split("async function startRemix", 1)[1].split("async function startLyricsSync", 1)[0])
        self.assertIn("not the original singer, mix, or vocal take", form)
        self.assertIn("English-like gibberish", form)
        self.assertIn('replace(/"[^"\\n]*"/g, "")', form)
        self.assertIn("X:|T:|M:|L:|Q:|V:|K:", form)
        self.assertIn("title={!songHasScore(song) ? REMIX_NO_SCORE", app)
        self.assertIn('className="menu-tip"', app)
        self.assertIn(".remix-dialog", css)
        self.assertIn("score.abc", main)
        self.assertIn("has_score", main)

    def test_cover_from_audio_uses_sheetsage_then_yue2(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        worker = (root / "python" / "sheetsage_worker.py").read_text(encoding="utf-8")
        engine = (root / "python" / "sheetsage.py").read_text(encoding="utf-8")
        catalog = (root / "python" / "model_catalog.json").read_text(encoding="utf-8")
        manager = (root / "python" / "model_manager.py").read_text(encoding="utf-8")
        self.assertIn("Cover from audio", app)
        self.assertIn("openAudioCover(song)", app)
        self.assertIn("transcribeCover", app)
        self.assertIn("local_files_only=True", worker)
        self.assertIn("base_model_path", worker)
        self.assertIn("prepare_local_parent", engine)
        transcribe = (root / "python" / "main.py").read_text(encoding="utf-8").split("def transcribe_cover_score", 1)[1].split("@app.get(\"/api/library/{folder}/score\")", 1)[0]
        self.assertIn("yue2_engine.unload()", transcribe)
        self.assertIn('["queued", "running"].includes(utilityJob.status)', app)
        self.assertIn("m-a-p/SheetSage2", catalog)
        self.assertIn("m-a-p/MERT-v2-FullSong", catalog)
        self.assertIn("'sheetsage':", manager)
        self.assertNotIn("render_assets", catalog)

    def test_sidecar_spawn_errors_have_a_persistent_diagnostic_command(self):
        host = (Path(__file__).resolve().parents[2] / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        self.assertIn("fn sidecar_error", host)
        self.assertIn('handle.emit("sidecar-error"', host)

    def test_generation_controls_are_applied_to_structured_conditioning(self):
        app = (Path(__file__).resolve().parents[2] / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("function applyDescriptionControls", app)
        self.assertIn("function buildStylePrompt", app)
        self.assertIn("${gender} voice", app)
        self.assertIn("no ${no}", app)
        self.assertIn("instrumental: true", app)
        self.assertNotIn("Principal Lead Gender Override", app)
        self.assertNotIn("Global Metadata", app.split("const STYLE_PRESETS", 1)[0])

    def test_more_options_uses_a_real_control_icon_and_animated_chevron(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (root / "src" / "App.css").read_text(encoding="utf-8")
        self.assertIn('className="options-sliders"', app)
        self.assertIn('className="options-chevron"', app)
        self.assertIn('aria-expanded={moreOptions}', app)
        self.assertNotIn('{moreOptions ? "⌃" : "⌄"}', app)
        self.assertIn(".more-options-button.open .options-chevron", css)

    def test_create_progress_stays_above_the_form_and_translation_does_not_overflow(self):
        root = Path(__file__).resolve().parents[2]
        app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (root / "src" / "App.css").read_text(encoding="utf-8")
        create_section = app.split('className={`composer main-view', 1)[1].split('className={`library-pane', 1)[0]
        self.assertLess(create_section.index("create-job-banner"), create_section.index("create-grid"))
        self.assertIn(".create-job-banner{position:sticky", css)
        self.assertIn(".translation-grid textarea{height:auto;min-height:110px}", css)
        self.assertNotIn(".create-lyrics label,.create-lyrics textarea{height:100%}", css)

    def test_job_timing_shows_elapsed_beside_remaining_prediction(self):
        app = (Path(__file__).resolve().parents[2] / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("function elapsedLabel(job: Job)", app)
        self.assertIn("function remainingLabel(job: Job)", app)
        self.assertIn('`${elapsedLabel(job)} elapsed · ${remaining}`', app)
        self.assertIn("<span>elapsed</span><b>{elapsedLabel(displayJob)}</b>", app)
        self.assertIn("<span>remaining</span><b>{remainingLabel(displayJob)", app)

    def test_setup_contract_includes_private_ffmpeg_and_yue2_model_layout(self):
        root = Path(__file__).resolve().parents[2]
        requirements = (root / "python" / "requirements.txt").read_text(encoding="utf-8")
        sources = (root / "MODEL_README.md").read_text(encoding="utf-8")
        self.assertIn("imageio-ffmpeg", requirements)
        self.assertIn("YuE2-3B", sources)
        self.assertIn("YuE2-Vae", sources)


if __name__ == "__main__":
    unittest.main()
