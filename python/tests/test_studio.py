from __future__ import annotations

import json
import math
import struct
import sys
from fastapi import HTTPException
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import main
import lyrics_sync
import stable_sfx
import stable_sfx_worker


class StudioTest(TestCase):
    def test_library_prefers_saved_score_abc_for_remix(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            song = root / "remix-source"
            song.mkdir()
            (song / "song.wav").write_bytes(b"RIFF" + b"audio" * 80)
            (song / "song.json").write_text(json.dumps({
                "id": "remix-source", "title": "Night Drive", "description": "city pop",
                "abc_score": "X:1\nK:C\nC D E", "created_at": "2026-09-13 12:00:00",
            }), encoding="utf-8")
            (song / "score.abc").write_text('X:1\nK:C\n"Am" A2 B2 |"G" G2 F2\n', encoding="utf-8")
            planned = (song / "score.abc").read_text(encoding="utf-8").strip()
            with patch.object(main, "LIBRARY_ROOT", root):
                items = main.library()
                score = main.song_planned_score("remix-source")
        self.assertEqual(1, len(items))
        self.assertTrue(items[0]["has_score"])
        self.assertNotEqual(planned, items[0].get("abc_score"))
        self.assertEqual(planned, score["abc"])

    def test_stable_sfx_worker_forces_prompt_encoder_to_local_folder(self) -> None:
        config = {"model": {"conditioning": {"configs": [{"type": "t5gemma", "config": {"repo_id": "remote/model", "subfolder": "remote-folder"}}]}}}
        localized = stable_sfx_worker.localize_model_config(config, Path("C:/local/sfx"))
        conditioner = localized["model"]["conditioning"]["configs"][0]["config"]
        self.assertNotIn("repo_id", conditioner)
        self.assertNotIn("subfolder", conditioner)
        self.assertEqual(str(Path("C:/local/sfx/t5gemma-b-b-ul2")), conditioner["model_path"])

    def test_stable_sfx_status_requires_model_config_weight_and_private_runtime(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); runtime = root / "stable_audio_3"; text_encoder = root / "t5gemma-b-b-ul2"
            with patch.object(stable_sfx, "MODEL_ROOT", root), patch.object(stable_sfx, "MODEL_FILE", root / "model.safetensors"), patch.object(stable_sfx, "MODEL_CONFIG", root / "model_config.json"), patch.object(stable_sfx, "TEXT_ENCODER_ROOT", text_encoder), patch.object(stable_sfx, "RUNTIME_PYTHON", root / "python.exe"), patch.object(stable_sfx, "RUNTIME_PACKAGE", runtime):
                self.assertFalse(stable_sfx.status()["ready"])
                (root / "model.safetensors").write_bytes(b"weights")
                (root / "model_config.json").write_text("{}", encoding="utf-8")
                text_encoder.mkdir()
                for name in stable_sfx.TEXT_ENCODER_FILES:
                    (text_encoder / name).write_bytes(b"local")
                (root / "python.exe").write_bytes(b"python")
                runtime.mkdir()
                ready = stable_sfx.status()
        self.assertTrue(ready["ready"])
        self.assertEqual("CPU", ready["processor"])

    def test_studio_sound_generation_queues_a_local_job_with_random_seed(self) -> None:
        from jobs import Job
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; song.mkdir()
            (song / "song.json").write_text("{}", encoding="utf-8")
            captured = {}
            def submit(kind, params, fn):
                captured.update({"kind": kind, "params": params, "fn": fn})
                return Job("sound-job", kind, params)
            request = main.SoundEffectRequest(prompt="A brass doorbell chime", duration=3)
            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main.stable_sfx, "status", return_value={"ready": True}), patch.object(main.manager, "submit", side_effect=submit):
                result = main.generate_studio_sound("song-one", request)
        self.assertEqual("stable_sfx", captured["kind"])
        self.assertIsInstance(captured["params"]["seed"], int)
        self.assertEqual("sound-job", result["job"]["id"])

    def test_effect_library_is_separate_and_can_copy_an_effect_into_studio(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); effects = root / "effects"; song = root / "song-one"
            effect = effects / "doorbell-1"; effect.mkdir(parents=True); song.mkdir()
            (effect / "effect.wav").write_bytes(b"RIFF" + b"audio" * 300)
            (effect / "effect.json").write_text(json.dumps({"id": "doorbell-1", "name": "Doorbell", "prompt": "A two-tone doorbell", "negative_prompt": "music", "duration": 2.0, "seed": 42, "created_at": "2026-08-14 12:00:00"}), encoding="utf-8")
            (song / "song.json").write_text("{}", encoding="utf-8")
            with patch.object(stable_sfx, "EFFECTS_ROOT", effects):
                listed = stable_sfx.list_effects()
                imported = stable_sfx.add_to_song("doorbell-1", song)
            metadata = json.loads((song / "song.json").read_text(encoding="utf-8"))
        self.assertEqual(["doorbell-1"], [item["id"] for item in listed])
        self.assertIn("doorbell", imported["file"])
        self.assertEqual("doorbell-1", metadata["studio_imports"][0]["effect_id"])

    def test_top_level_effect_generation_queues_without_a_song(self) -> None:
        from jobs import Job
        captured = {}
        def submit(kind, params, fn):
            captured.update({"kind": kind, "params": params, "fn": fn})
            return Job("effect-job", kind, params)
        request = main.SoundEffectRequest(prompt="A close thunder crack", duration=4)
        with patch.object(main.stable_sfx, "status", return_value={"ready": True}), patch.object(main.manager, "submit", side_effect=submit):
            result = main.generate_effect(request)
        self.assertEqual("stable_sfx", captured["kind"])
        self.assertEqual("effect-job", result["job"]["id"])
        self.assertIsInstance(captured["params"]["seed"], int)

    def test_queued_sfx_job_is_logged_as_a_sound_effect(self) -> None:
        import jobs as jobs_mod
        with self.assertLogs("yue2.jobs", level="INFO") as captured:
            job = jobs_mod.manager.submit("stable_sfx", {"prompt": "boots"}, lambda active: {"ok": True})
        self.assertTrue(any("Queued sound effect job" in line and job.id[:8] in line for line in captured.output))
        self.assertFalse(any(f"Queued YuE2 job {job.id[:8]}" in line for line in captured.output))

    def test_sound_effect_generation_writes_worker_output_to_the_log(self) -> None:
        from jobs import Job
        from tempfile import TemporaryDirectory
        class FinishingLines:
            def __init__(self, lines: list[str], on_done):
                self._lines = list(lines)
                self._on_done = on_done
            def __iter__(self):
                yield from self._lines
                self._on_done()
        class FakeProcess:
            def __init__(self, target: Path):
                self.pid = 4242
                self._code = None
                def finish() -> None:
                    self._code = 0
                self.stdout = FinishingLines([
                    "loading encoder",
                    'SFX_PROGRESS {"phase": "Sampling", "progress": 0.4}',
                    "wrote wav",
                ], finish)
                self._target = target
            def poll(self):
                return self._code
            def wait(self):
                self._target.write_bytes(b"RIFF" + b"audio" * 400)
                self._code = 0
                return 0
        with TemporaryDirectory() as temp:
            effects = Path(temp) / "effects"
            job = Job("sfxjob01deadbeef", "stable_sfx", {
                "prompt": "boots of soldiers locked in step across dirt",
                "duration": 2.0,
                "seed": 7,
                "name": "Boots",
                "negative_prompt": "music",
            })
            def fake_popen(command, **_kwargs):
                return FakeProcess(Path(command[command.index("--output") + 1]))
            with patch.object(stable_sfx, "EFFECTS_ROOT", effects), patch.object(stable_sfx, "status", return_value={"ready": True}), patch.object(stable_sfx.subprocess, "Popen", side_effect=fake_popen), self.assertLogs("yue2.sfx", level="INFO") as captured:
                result = stable_sfx.generate(job)
        self.assertEqual("Boots", result["name"])
        joined = "\n".join(captured.output)
        self.assertIn("Generating sound effect 'Boots'", joined)
        self.assertIn("[sfx] loading encoder", joined)
        self.assertIn("[sfx] Sampling", joined)
        self.assertIn("Saved sound effect:", joined)

    def test_studio_playhead_keeps_the_animation_loop_alive_after_the_song_ends(self) -> None:
        source = (PYTHON_ROOT.parent / "src" / "SongStudio.tsx").read_text(encoding="utf-8")
        follow = source.split("const follow = () => {", 1)[1]
        follow = follow.split("useEffect(() => { animation.current = requestAnimationFrame(follow)", 1)[0]
        first_raf = follow.find("requestAnimationFrame(follow)")
        end_guard = follow.find("timelineTime >= contentEnd")
        self.assertGreater(first_raf, -1)
        self.assertGreater(end_guard, -1)
        self.assertLess(first_raf, end_guard, "follow() must schedule the next frame before the song-end return")
        self.assertIn("clockRef.current.running && timelineTime >= contentEnd", follow)
        arm = source.split("const armClock = ", 1)[1].split("const togglePlayback", 1)[0]
        self.assertIn("requestAnimationFrame(follow)", arm)

    def test_song_menu_uses_nested_download_formats_without_placeholder_actions(self) -> None:
        source = (PYTHON_ROOT.parent / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("song-download-menu", source)
        self.assertIn("Download WAV", source)
        self.assertIn("Download MP3", source)
        self.assertIn("Download FLAC", source)
        self.assertNotIn("Video Studio will be copied from KAS next", source)
        self.assertNotIn("Playlists are not connected yet", source)

    def test_translation_lines_ignore_section_tags_and_follow_sung_lines(self) -> None:
        payload = {
            "lines": [
                {"text": "Kom heim", "start": 1.0, "end": 2.0, "words": []},
                {"text": "yfir stein", "start": 2.2, "end": 3.1, "words": []},
            ]
        }
        translated = lyrics_sync.attach_translations(
            payload,
            "[Chorus]\nCome home\n\nover stone",
        )
        self.assertEqual("Come home", translated["lines"][0]["translation"])
        self.assertEqual("over stone", translated["lines"][1]["translation"])
        self.assertEqual(2, translated["translation_line_count"])

    def test_rich_lyric_directions_are_removed_from_words_to_sing(self) -> None:
        source = """[Start]\n[Fade In]\n[Intro – Female alto alone, immediate and close]\nKom heim\n\n[Verse 1 – Female chant, controlled]\nVið hliðit kom\n\n[Bridge – Ritual call and response]\n[Female – clear, ceremonial]\nHestr við hlið\n[Male – deep undertone]\nKom\n\n[Fade Out]\n[End]"""
        cleaned, directions = main.prepare_music3_lyrics(source)
        self.assertEqual("[Intro]\nKom heim\n\n[Verse]\nVið hliðit kom\n\n[Bridge]\nHestr við hlið\nKom", cleaned)
        self.assertNotIn("Female alto alone", cleaned)
        self.assertIn("Intro: Female alto alone, immediate and close", directions)
        self.assertIn("Bridge, Singer A (Female): clear, ceremonial", directions)
        self.assertIn("Bridge, Singer B (Male): deep undertone", directions)
        self.assertIn("Ending: fade out", directions)

    def test_concise_performance_tags_move_to_caption_instructions(self) -> None:
        source = "[Verse]\nFour\n[Spoken Countdown]\n4, 3, 2, 1\n[Whispered]\ncome closer"
        cleaned, directions = main.prepare_music3_lyrics(source)
        self.assertEqual("[Verse]\nFour\n4, 3, 2, 1\ncome closer", cleaned)
        self.assertIn("Verse, Spoken Countdown: perform the following lyric line in this style", directions)
        self.assertIn("Verse, Whispered: perform the following lyric line in this style", directions)

    def test_official_hyphenated_transition_tags_survive(self) -> None:
        source = "[Verse]\nA\n[Pre-Chorus]\nB\n[Chorus]\nC\n[Post-Chorus]\nD"
        cleaned, directions = main.prepare_music3_lyrics(source)
        self.assertEqual(source, cleaned)
        self.assertEqual([], directions)

    def test_extracted_stage_directions_are_caption_instructions(self) -> None:
        caption = main.music3_caption("Nordic ritual folk.", ["Chorus: female opens into a rising hook"])
        self.assertIn("Nordic ritual folk", caption)
        self.assertIn("style, not lyrics", caption)
        self.assertNotIn("Global Metadata", caption)

    def test_extracted_directions_append_to_compact_style(self) -> None:
        description = "Global Metadata\nBasic Attributes: Nordic folk.\n\nVocal Details\nVocal Gender & Timbre: Singer A (Female).\n\nArrangement\nInstrument Lifecycle: bowed lyre."
        caption = main.music3_caption(description, ["Bridge: Singer B answers Singer A"])
        self.assertIn("Nordic folk", caption)
        self.assertIn("bowed lyre", caption)
        self.assertIn("Bridge: Singer B answers Singer A", caption)
        self.assertNotIn("Global Metadata", caption)
        self.assertNotIn("Vocal Details", caption)

    def test_cancel_only_signals_yue2_engine_for_music_jobs(self) -> None:
        from fastapi.testclient import TestClient
        from jobs import Job
        client = TestClient(main.app)
        cover = Job("cover-cancel", "cover_art", {})
        cover.status = "running"
        with patch.object(main.manager, "get", return_value=cover), patch.object(main.manager, "cancel_job", return_value=True), patch.object(main.yue2_engine, "cancel") as cancel:
            self.assertEqual(200, client.post("/api/jobs/cover-cancel/cancel").status_code)
            cancel.assert_not_called()

    def test_audio_export_creates_mp3_and_flac(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            song = Path(temp)
            (song / "song.wav").write_bytes(b"wav")
            commands = []
            def fake_run(command, **_kwargs):
                commands.append(command)
                Path(command[-1]).write_bytes(b"encoded")
                return type("Result", (), {"returncode": 0, "stderr": ""})()
            with patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                (song / "cover.png").write_bytes(b"cover")
                (song / "song.json").write_text(json.dumps({"title": "My Song", "artist": "The Artist", "album": "The Album", "genre": "Dark Folk", "year": "2026", "track_number": "2/10", "description": "A local song", "cover": "cover.png"}), encoding="utf-8")
                for fmt in ("mp3", "flac"):
                    result = main.export_audio(song, fmt)
                    self.assertEqual(f"My Song.{fmt}", result["filename"])
            mp3 = commands[0]
            self.assertIn("-q:a", mp3)
            self.assertEqual("0", mp3[mp3.index("-q:a") + 1])
            self.assertIn("artist=The Artist", mp3)
            self.assertIn("album=The Album", mp3)
            self.assertIn("genre=Dark Folk", mp3)
            self.assertIn("date=2026", mp3)
            self.assertIn("track=2/10", mp3)
            self.assertIn("attached_pic", mp3)

    def test_uploaded_cover_is_normalized_and_saved_for_future_exports(self) -> None:
        from fastapi.testclient import TestClient
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; song.mkdir()
            (song / "song.json").write_text(json.dumps({"id": "one", "title": "Song", "cover": None}), encoding="utf-8")
            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"normalized-cover")
                return type("Result", (), {"returncode": 0, "stderr": ""})()
            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                response = TestClient(main.app).post("/api/library/song-one/cover/upload?filename=my-art.jpg", content=b"image-bytes", headers={"Content-Type": "image/jpeg"})
            saved = json.loads((song / "song.json").read_text(encoding="utf-8"))
        self.assertEqual(200, response.status_code)
        self.assertEqual("cover.png", saved["cover"])
        self.assertIn("?v=", response.json()["cover_url"])

    def test_studio_session_is_saved_with_the_song(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; song.mkdir()
            (song / "song.json").write_text(json.dumps({"title": "Studio Song"}), encoding="utf-8")
            request = main.StudioSessionRequest(tracks=[main.StudioTrackState(name="vocals.wav", gain=.8, muted=False, solo=True)])
            with patch.object(main, "LIBRARY_ROOT", root):
                result = main.save_studio_session("song-one", request)
            saved = json.loads((song / "song.json").read_text(encoding="utf-8"))
        self.assertTrue(result["saved"])
        self.assertEqual(.8, saved["studio"]["tracks"][0]["gain"])
        self.assertTrue(saved["studio"]["tracks"][0]["solo"])

    def test_studio_bounce_uses_only_audible_stem_lanes(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; stems = song / "stems" / "htdemucs"; stems.mkdir(parents=True)
            for name in ("vocals.wav", "drums.wav", "bass.wav", "other.wav"):
                (stems / name).write_bytes(b"wav")
            (song / "song.json").write_text(json.dumps({"title": "Studio Song", "stems": ["vocals.wav", "drums.wav", "bass.wav", "other.wav"]}), encoding="utf-8")
            request = main.StudioBounceRequest(variant="custom", tracks=[
                main.StudioTrackState(name="vocals.wav", gain=.9, muted=True),
                main.StudioTrackState(name="drums.wav", gain=.7),
                main.StudioTrackState(name="bass.wav", gain=.85),
                main.StudioTrackState(name="other.wav", gain=1.0, muted=True),
            ])
            commands = []
            def fake_run(command, **_kwargs):
                commands.append(command); Path(command[-1]).write_bytes(b"mix")
                return type("Result", (), {"returncode": 0, "stderr": ""})()
            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                result = main.bounce_studio_mix("song-one", request)
            saved = json.loads((song / "song.json").read_text(encoding="utf-8"))
        command = commands[0]
        input_paths = {Path(value).resolve() for value in command if isinstance(value, str) and value.endswith(".wav")}
        self.assertIn((stems / "drums.wav").resolve(), input_paths)
        self.assertIn((stems / "bass.wav").resolve(), input_paths)
        self.assertNotIn((stems / "vocals.wav").resolve(), input_paths)
        self.assertIn("custom", result["filename"])
        self.assertEqual("custom", saved["studio_mixes"][0]["variant"])

    def test_custom_bounce_saves_a_new_library_song_and_leaves_the_original(self) -> None:
        """A full bounce is a new song, not an overwrite.

        Studio is for trying things. An export that replaces the take you were
        working from leaves nowhere to go back to, and nothing new shows up in
        the library where the user expects to find it.
        """
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; stems = song / "stems" / "htdemucs"; stems.mkdir(parents=True)
            (song / "song.wav").write_bytes(b"dry-original")
            (song / "cover.png").write_bytes(b"art")
            (stems / "vocals.wav").write_bytes(b"stem")
            (song / "song.json").write_text(json.dumps({
                "title": "Studio Song", "audio": "song.wav", "cover": "cover.png",
                "artist": "The Kraken", "stems": ["vocals.wav"],
            }), encoding="utf-8")
            request = main.StudioBounceRequest(variant="custom", tracks=[main.StudioTrackState(name="vocals.wav")])

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"wet-mix")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                result = main.bounce_studio_mix("song-one", request)
                original_audio = (song / "song.wav").read_bytes()
                exported_dir = root / result["exported_folder"]
                exported = json.loads((exported_dir / "song.json").read_text(encoding="utf-8"))
                exported_audio = (exported_dir / exported["audio"]).read_bytes()
                titles = sorted(item["title"] for item in main.library())

        self.assertTrue(result["exported"])
        self.assertEqual("Studio Song (Studio Mix)", result["exported_title"])
        # The source take is untouched -- same bytes, no promotion, no backup needed.
        self.assertEqual(b"dry-original", original_audio)
        self.assertFalse((song / "studio" / "original_mix.wav").exists())
        # The export is a real, separate library entry carrying the song's identity.
        self.assertEqual(b"wet-mix", exported_audio)
        self.assertEqual("The Kraken", exported["artist"])
        self.assertEqual("cover.png", exported["cover"])
        self.assertEqual("song-one", exported["studio_source"])
        self.assertEqual(["Studio Song", "Studio Song (Studio Mix)"], titles)
        # Editing state belongs to the take it came from, not to the bounce.
        for key in ("studio", "studio_mixes", "stems"):
            self.assertNotIn(key, exported)

    def test_repeat_custom_bounces_get_numbered_titles(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; stems = song / "stems" / "htdemucs"; stems.mkdir(parents=True)
            (song / "song.wav").write_bytes(b"dry-original")
            (stems / "vocals.wav").write_bytes(b"stem")
            (song / "song.json").write_text(json.dumps({"title": "Studio Song", "audio": "song.wav", "stems": ["vocals.wav"]}), encoding="utf-8")
            request = main.StudioBounceRequest(variant="custom", tracks=[main.StudioTrackState(name="vocals.wav")])

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"wet-mix")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                first = main.bounce_studio_mix("song-one", request)
                second = main.bounce_studio_mix("song-one", request)
        self.assertEqual("Studio Song (Studio Mix)", first["exported_title"])
        self.assertEqual("Studio Song (Studio Mix 2)", second["exported_title"])

    def test_instrumental_and_range_bounces_do_not_replace_song_audio(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; stems = song / "stems" / "htdemucs"; stems.mkdir(parents=True)
            (song / "song.wav").write_bytes(b"dry-original")
            (stems / "vocals.wav").write_bytes(b"vox")
            (stems / "drums.wav").write_bytes(b"drm")
            (song / "song.json").write_text(json.dumps({"title": "Studio Song", "audio": "song.wav", "stems": ["vocals.wav", "drums.wav"]}), encoding="utf-8")

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"sidecar")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                instrumental = main.bounce_studio_mix("song-one", main.StudioBounceRequest(variant="instrumental", tracks=[main.StudioTrackState(name="drums.wav")]))
                ranged = main.bounce_studio_mix("song-one", main.StudioBounceRequest(variant="custom", selection=main.StudioRange(start=1, end=2), tracks=[main.StudioTrackState(name="vocals.wav")]))
                original = (song / "song.wav").read_bytes()
                backup_exists = (song / "studio" / "original_mix.wav").exists()
        self.assertFalse(instrumental.get("promoted"))
        self.assertFalse(ranged.get("promoted"))
        self.assertEqual(b"dry-original", original)
        self.assertFalse(backup_exists)

    def test_studio_import_keeps_source_and_prepares_editable_wav(self) -> None:
        from fastapi.testclient import TestClient
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; song.mkdir()
            (song / "song.json").write_text(json.dumps({"title": "Studio Song"}), encoding="utf-8")

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"RIFF prepared")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                response = TestClient(main.app).post("/api/library/song-one/studio/import?filename=Doorbell.mp3", content=b"pretend audio", headers={"Content-Type": "audio/mpeg"})

            saved = json.loads((song / "song.json").read_text(encoding="utf-8"))
            entry = saved["studio_imports"][0]
            prepared = song / "studio" / "tracks" / entry["file"]
            original = song / "studio" / "imports" / entry["original"]
        self.assertEqual(200, response.status_code)
        self.assertEqual("Doorbell", response.json()["name"])
        self.assertTrue(prepared.name.endswith("_doorbell.wav"))
        self.assertTrue(original.name.endswith("_doorbell.mp3"))

    def test_studio_bounce_honors_track_edits_and_selected_range(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; tracks = song / "studio" / "tracks"; tracks.mkdir(parents=True)
            imported = tracks / "doorbell.wav"; imported.write_bytes(b"wav")
            (song / "song.json").write_text(json.dumps({"title": "Studio Song", "studio_imports": [{"file": imported.name, "name": "Doorbell"}]}), encoding="utf-8")
            request = main.StudioBounceRequest(
                variant="custom",
                selection=main.StudioRange(start=10, end=20),
                tracks=[main.StudioTrackState(name=imported.name, gain=.75, offset=2.5, trim_start=3.0, trim_end=12.5, fade_in=1.25, fade_out=2.0, cuts=[main.StudioRange(start=7, end=8)])],
            )
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command); Path(command[-1]).write_bytes(b"mix")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                main.bounce_studio_mix("song-one", request)
        graph = commands[0][commands[0].index("-filter_complex") + 1]
        self.assertIn("volume=0.75000", graph)
        self.assertIn("between(t,4.50000,5.50000)", graph)
        self.assertIn("afade=t=in:st=0.50000:d=1.25000", graph)
        self.assertIn("afade=t=out:st=8.00000:d=2.00000", graph)
        self.assertIn("adelay=2500:all=1", graph)
        self.assertIn("atrim=start=10.00000:end=20.00000", graph)

    def test_legacy_session_migrates_offset_trim_and_cuts_into_clips(self) -> None:
        track = main.StudioTrackState(name="vocals.wav", offset=3, trim_start=3, trim_end=13, fade_in=1, fade_out=2, cuts=[main.StudioRange(start=7, end=8)])
        clips = main.resolve_studio_clips(track)
        self.assertEqual(2, len(clips))
        self.assertEqual(3.0, clips[0].start)
        self.assertEqual(0.0, clips[0].source_in)
        self.assertAlmostEqual(4.0, clips[0].source_out)
        self.assertEqual(8.0, clips[1].start)
        self.assertAlmostEqual(5.0, clips[1].source_in)

    def test_studio_bounce_places_split_clips_and_does_not_pad_the_workspace(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; tracks = song / "studio" / "tracks"; tracks.mkdir(parents=True)
            imported = tracks / "count.wav"; imported.write_bytes(b"wav")
            (song / "song.json").write_text(json.dumps({"title": "Studio Song", "audio": "song.wav", "studio_imports": [{"file": imported.name, "name": "Count"}]}), encoding="utf-8")
            (song / "song.wav").write_bytes(b"song")
            request = main.StudioBounceRequest(tracks=[
                main.StudioTrackState(name="song.wav", use_clips=True, clips=[main.StudioClip(id="song-a", start=3, source_in=0, source_out=60, fade_in=0.5, fade_out=0)]),
                main.StudioTrackState(name=imported.name, use_clips=True, clips=[main.StudioClip(id="count-a", start=0, source_in=0, source_out=3)]),
            ])
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command); Path(command[-1]).write_bytes(b"mix")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                main.bounce_studio_mix("song-one", request)
        graph = commands[0][commands[0].index("-filter_complex") + 1]
        self.assertIn("atrim=start=0.00000:end=60.00000", graph)
        self.assertIn("adelay=3000:all=1", graph)
        self.assertIn("afade=t=in:st=0:d=0.50000:curve=qsin", graph)
        self.assertIn("atrim=start=0.00000:end=3.00000", graph)
        self.assertNotIn("apad", graph)

    def test_custom_mix_can_combine_original_song_with_imported_audio(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; imported_root = song / "studio" / "tracks"; imported_root.mkdir(parents=True)
            original = song / "song.wav"; imported = imported_root / "car.wav"
            original.write_bytes(b"song"); imported.write_bytes(b"effect")
            (song / "song.json").write_text(json.dumps({"title": "Studio Song", "audio": "song.wav", "studio_imports": [{"file": "car.wav", "name": "Car"}]}), encoding="utf-8")
            request = main.StudioBounceRequest(tracks=[main.StudioTrackState(name="song.wav"), main.StudioTrackState(name="car.wav", offset=8)])
            command = []

            def fake_run(args, **_kwargs):
                command.extend(args); Path(args[-1]).write_bytes(b"mix")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                main.bounce_studio_mix("song-one", request)
        inputs = [Path(command[index + 1]).name for index, value in enumerate(command[:-1]) if value == "-i"]
        self.assertEqual(["song.wav", "car.wav"], inputs)

    def test_original_reference_is_never_doubled_after_stems_exist(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; stems = song / "stems" / "htdemucs"; stems.mkdir(parents=True)
            (song / "song.wav").write_bytes(b"song"); (stems / "vocals.wav").write_bytes(b"stem")
            (song / "song.json").write_text(json.dumps({"title": "Studio Song", "audio": "song.wav", "stems": ["vocals.wav"]}), encoding="utf-8")
            request = main.StudioBounceRequest(tracks=[main.StudioTrackState(name="song.wav"), main.StudioTrackState(name="vocals.wav")])
            command = []

            def fake_run(args, **_kwargs):
                command.extend(args); Path(args[-1]).write_bytes(b"mix")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main, "ffmpeg_path", return_value="ffmpeg"), patch.object(main.subprocess, "run", side_effect=fake_run):
                main.bounce_studio_mix("song-one", request)
        inputs = [Path(command[index + 1]).name for index, value in enumerate(command[:-1]) if value == "-i"]
        self.assertEqual(["vocals.wav"], inputs)

    def test_real_ffmpeg_bounce_accepts_every_region_effect(self) -> None:
        if not main.ffmpeg_path(): self.skipTest("FFmpeg is not installed")
        import wave
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; stems = song / "stems" / "htdemucs"; stems.mkdir(parents=True)
            source = stems / "vocals.wav"
            with wave.open(str(source), "wb") as handle:
                handle.setnchannels(2); handle.setsampwidth(2); handle.setframerate(44100)
                frames = bytearray()
                for index in range(44100 * 2):
                    value = int(math.sin(index * 2 * math.pi * 440 / 44100) * 6000)
                    frames.extend(struct.pack("<hh", value, value))
                handle.writeframes(frames)
            (song / "song.json").write_text(json.dumps({"title": "Effects", "stems": ["vocals.wav"]}), encoding="utf-8")
            effects = [main.StudioEffectRegion(id=f"fx-{kind}", kind=kind, amount=.5, start=.2, end=1.2) for kind in ("gain_up", "gain_down", "clarity", "auto_level", "echo", "reverb", "compressor", "normalize", "auto_pan", "low_pass", "high_pass", "telephone", "saturation", "tremolo", "stereo_widen", "limiter")]
            request = main.StudioBounceRequest(tracks=[main.StudioTrackState(name="vocals.wav", effects=effects)])
            with patch.object(main, "LIBRARY_ROOT", root):
                result = main.bounce_studio_mix("song-one", request)
            output = next((song / "mixes").glob("*.wav"))
            with wave.open(str(output), "rb") as handle:
                frame_count = handle.getnframes(); channels = handle.getnchannels()
        self.assertGreater(frame_count, 44100)
        self.assertEqual(2, channels)
        self.assertIn("custom", result["filename"])

    def test_region_effect_keeps_number_and_user_selected_fades(self) -> None:
        effect = main.StudioEffectRegion(
            id="echo-3", kind="echo", amount=.6, instance=3,
            start=2, end=6, fade_in=.75, fade_out=0,
        )
        saved = effect.model_dump()
        self.assertEqual(3, saved["instance"])
        self.assertEqual(.75, saved["fade_in"])
        self.assertEqual(0, saved["fade_out"])
        envelope = main._effect_envelope(2, 6, effect.fade_in, effect.fade_out)
        self.assertIn("clip((t-2.00000)/0.75000", envelope)
        self.assertNotIn("6.00000-t)/", envelope)

    def test_region_effect_can_have_no_automatic_fades(self) -> None:
        self.assertEqual(
            "between(t,1.00000,4.00000)",
            main._effect_envelope(1, 4, 0, 0),
        )

    def test_removing_imported_track_cleans_only_the_studios_local_copies(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp); song = root / "song-one"; imported_root = song / "studio" / "tracks"; source_root = song / "studio" / "imports"
            imported_root.mkdir(parents=True); source_root.mkdir(parents=True)
            (imported_root / "doorbell.wav").write_bytes(b"prepared"); (source_root / "doorbell.mp3").write_bytes(b"copy")
            (song / "song.json").write_text(json.dumps({"title": "Studio Song", "studio_imports": [{"file": "doorbell.wav", "name": "Doorbell", "original": "doorbell.mp3"}]}), encoding="utf-8")
            with patch.object(main, "LIBRARY_ROOT", root):
                result = main.remove_studio_track("song-one", "doorbell.wav")
            saved = json.loads((song / "song.json").read_text(encoding="utf-8"))
            prepared_exists = (imported_root / "doorbell.wav").exists(); copied_source_exists = (source_root / "doorbell.mp3").exists()
        self.assertTrue(result["removed"])
        self.assertFalse(prepared_exists)
        self.assertFalse(copied_source_exists)
        self.assertEqual([], saved["studio_imports"])

    def test_wav_inspection_uses_actual_duration_and_accepts_quiet_audio(self) -> None:
        import struct
        import wave
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            audible = Path(temp) / "audible.wav"
            silent = Path(temp) / "silent.wav"
            for path, value in ((audible, 1200), (silent, 0)):
                with wave.open(str(path), "wb") as handle:
                    handle.setnchannels(2); handle.setsampwidth(2); handle.setframerate(1000)
                    handle.writeframes(struct.pack("<h", value) * 2000)
            self.assertAlmostEqual(1.0, main.yue2_engine.inspect_wav(audible)["duration"])
            self.assertAlmostEqual(1.0, main.yue2_engine.inspect_wav(silent)["duration"])

    def test_prompt_limit_is_checked_before_job_submission(self) -> None:
        request = main.GenerateRequest(description="A song", lyrics="words")
        with patch.object(main.yue2_engine, "count_prompt_tokens", return_value={"tokens": 24577, "maximum": 24576}):
            with self.assertRaisesRegex(HTTPException, "24,577"):
                main.prepare_generation_params(request.model_dump())

    def test_unicode_prompt_text_is_preserved_for_yue2(self) -> None:
        request = main.GenerateRequest(
            description='A vocal answers “through” with a dark pulse.',
            lyrics='[Verse – close]\nWe’ll go “through”.',
        )
        with patch.object(main.yue2_engine, "count_prompt_tokens", return_value={"tokens": 42, "maximum": 24576}) as counter:
            prepared = main.prepare_generation_params(request.model_dump())
        caption, lyrics, cot_mode, abc_score = counter.call_args.args
        self.assertEqual("full", cot_mode)
        self.assertIsNone(abc_score)
        self.assertIn("“through”", caption)
        self.assertIn("close", caption)
        self.assertIn("[Verse]", lyrics)
        self.assertIn("We’ll go", lyrics)
        self.assertNotIn("[Verse –", lyrics)
        self.assertIn("“through”", prepared["description"])
        self.assertIn("We’ll", prepared["lyrics"])
        self.assertIn("–", prepared["lyrics"])

    def test_yue2_worker_pipes_are_forced_to_utf8_on_windows(self) -> None:
        environment = main.yue2_engine._env()
        self.assertEqual("utf-8", environment["PYTHONIOENCODING"])
        self.assertEqual("1", environment["PYTHONUTF8"])

    def test_stem_worker_pipes_are_forced_to_utf8_on_windows(self) -> None:
        source = (PYTHON_ROOT / "main.py").read_text(encoding="utf-8")
        runner = (PYTHON_ROOT / "demucs_runner.py").read_text(encoding="utf-8")
        self.assertIn('"PYTHONIOENCODING": "utf-8"', source)
        self.assertIn("_configure_stdio", runner)

    def test_lyrics_sync_worker_pipes_are_forced_to_utf8_on_windows(self) -> None:
        bridge = (PYTHON_ROOT / "lyrics_sync.py").read_text(encoding="utf-8")
        worker = (PYTHON_ROOT / "lyrics_align_worker.py").read_text(encoding="utf-8")
        self.assertIn('"PYTHONIOENCODING": "utf-8"', bridge)
        self.assertIn('"PYTHONUTF8": "1"', bridge)
        self.assertIn("ensure_ascii=True", worker)
        self.assertIn("_configure_stdio", worker)

    def test_cover_prompt_uses_structured_description_fields(self) -> None:
        description = "Global Metadata\nBasic Attributes: Nordic ritual folk, 54 BPM.\nGlobal Emotional Progression: cold grief.\n\nVocal Details\nSinger A.\n\nArrangement\nSparse drum."
        prompt = main.cover_art.build_prompt("Kom Heim", description, "[Verse]\nKom heim")
        self.assertIn("Nordic ritual folk", prompt)
        self.assertIn("cold grief", prompt)
        self.assertNotIn(", Global Metadata,", prompt)
    def test_retired_browser_editor_is_not_mounted(self) -> None:
        self.assertFalse(hasattr(main, "EDITOR_DIR"))
        self.assertNotIn("/editor", {route.path for route in main.app.routes})

    def test_model_status_names_every_required_component(self) -> None:
        missing = Path("Z:/definitely-missing-yue2")
        model_files = {
            "diffusion": missing / "dit.safetensors",
            "text_encoder": missing / "text.safetensors",
            "decoder": missing / "dav.safetensors",
        }
        with patch.dict(main.yue2_engine.MODEL_FILES, model_files, clear=True):
            status = main.yue2_engine.model_status()
        self.assertFalse(status["ready"])
        self.assertEqual(status["required"], len(status["missing"]))
        self.assertEqual(["diffusion", "text_encoder", "decoder"], status["missing"])

    def test_library_ignores_broken_manifests(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            broken = root / "bad"
            broken.mkdir()
            (broken / "song.json").write_text("not json", encoding="utf-8")
            with patch.object(main, "LIBRARY_ROOT", root):
                self.assertEqual([], main.library())

    def test_orphan_cleanup_removes_only_incomplete_folders(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            incomplete = root / "incomplete"; incomplete.mkdir(); (incomplete / "song.wav").write_bytes(b"RIFF")
            complete = root / "complete"; complete.mkdir(); (complete / "song.json").write_text("{}", encoding="utf-8")
            with patch.object(main, "LIBRARY_ROOT", root):
                self.assertEqual(1, main.cleanup_orphan_library())
            self.assertFalse(incomplete.exists())
            self.assertTrue(complete.exists())

    def test_song_folders_use_titles_and_preserve_duplicate_takes(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp, patch.object(main, "LIBRARY_ROOT", Path(temp)):
            first = main.create_song_directory("Terminal Pull")
            (first / "keep.txt").write_text("original")
            second = main.create_song_directory("Terminal Pull")
            self.assertEqual("Terminal Pull", first.name)
            self.assertEqual("Terminal Pull (2)", second.name)
            self.assertEqual("original", (first / "keep.txt").read_text())
            self.assertEqual("今晚不眠", main.create_song_directory("今晚不眠").name)
            safe = main.create_song_directory("../CON.txt")
            self.assertEqual(Path(temp).resolve(), safe.resolve().parent)
            self.assertEqual("Song CON.txt", main.create_song_directory("CON.txt").name)

    def test_generate_names_wav_after_title(self) -> None:
        from jobs import Job
        from tempfile import TemporaryDirectory

        def fake_generate(job, request, output):
            output.write_bytes(b"RIFF")
            return {"duration": 12, "sample_rate": 44100}

        params = main.GenerateRequest(title="Kom Heim", description="A song").model_dump()
        params["seed"] = 1
        job = Job("abcdef123456", "yue2", params)
        with TemporaryDirectory() as temp, patch.object(main, "LIBRARY_ROOT", Path(temp)), patch.object(main.yue2_engine, "generate", side_effect=fake_generate), patch.object(main.cover_art, "available", return_value=False):
            result = main.generate(job)
            folder = Path(result["folder"])
            self.assertEqual("Kom Heim.wav", result["audio"])
            self.assertTrue(result["audio_url"].split("?", 1)[0].endswith("/Kom%20Heim.wav"))
            self.assertTrue((folder / "Kom Heim.wav").is_file())
            self.assertFalse((folder / "song.wav").exists())

    def test_failed_generation_removes_its_incomplete_folder(self) -> None:
        from jobs import Job
        from tempfile import TemporaryDirectory
        params = main.GenerateRequest(description="A song").model_dump()
        params["seed"] = 1
        job = Job("abcdef123456", "yue2", params)
        with TemporaryDirectory() as temp, patch.object(main, "LIBRARY_ROOT", Path(temp)), patch.object(main.ai_assist, "ensure_unique_title", lambda title, **kw: title), patch.object(main.yue2_engine, "generate", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                main.generate(job)
            self.assertEqual([], list(Path(temp).iterdir()))

    def test_library_exposes_saved_wav(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "song-one"
            folder.mkdir()
            (folder / "song.wav").write_bytes(b"RIFF")
            (folder / "song.json").write_text(json.dumps({"id": "one", "title": "One", "audio": "song.wav", "created_at": "2026"}), encoding="utf-8")
            with patch.object(main, "LIBRARY_ROOT", root):
                items = main.library()
            self.assertEqual("One", items[0]["title"])
            self.assertEqual("/api/library/song-one/One.wav", items[0]["audio_url"].split("?", 1)[0])
            self.assertIsNone(items[0]["original_audio_url"])
            self.assertEqual("song-one", items[0]["folder_name"])
            self.assertTrue((folder / "One.wav").is_file())
            self.assertFalse((folder / "song.wav").exists())

    def test_library_supports_genre_nested_song_folders(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "EDM" / "Neon Horizon"
            folder.mkdir(parents=True)
            (folder / "song.wav").write_bytes(b"RIFF")
            (folder / "song.json").write_text(json.dumps({"id": "one", "title": "Neon Horizon", "genre": "EDM", "audio": "song.wav", "created_at": "2026"}), encoding="utf-8")
            with patch.object(main, "LIBRARY_ROOT", root):
                items = main.library()
                resolved = main.resolve_song_folder("EDM/Neon Horizon")
            self.assertEqual("EDM/Neon Horizon", items[0]["folder_name"])
            self.assertEqual("/api/library/EDM%2FNeon%20Horizon/Neon%20Horizon.wav", items[0]["audio_url"].split("?", 1)[0])
            self.assertEqual(folder.resolve(), resolved.resolve())

    def test_song_details_can_be_updated(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "song-one"
            folder.mkdir()
            (folder / "song.wav").write_bytes(b"RIFF")
            (folder / "song.json").write_text(json.dumps({"id": "one", "title": "Old", "audio": "song.wav"}), encoding="utf-8")
            with patch.object(main, "LIBRARY_ROOT", root):
                result = main.update_song("song-one", main.SongUpdateRequest(title="New", artist="Kraken", album="Sea Songs", genre="Ritual folk", year="2026", track_number="3", description="Changed", lyrics="Words"))
            saved = json.loads((folder / "song.json").read_text(encoding="utf-8"))
            self.assertTrue(result["updated"])
            self.assertEqual("New", saved["title"])
            self.assertEqual("New.wav", saved["audio"])
            self.assertTrue((folder / "New.wav").is_file())
            self.assertFalse((folder / "song.wav").exists())
            self.assertEqual("Changed", saved["description"])
            self.assertEqual("Kraken", saved["artist"])
            self.assertEqual("Sea Songs", saved["album"])
            self.assertEqual("Ritual folk", saved["genre"])
            self.assertEqual("2026", saved["year"])
            self.assertEqual("3", saved["track_number"])

    def test_editing_translation_updates_timed_lines_without_resync(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "song-one"
            sync = folder / "lyrics_sync"
            sync.mkdir(parents=True)
            (folder / "song.json").write_text(json.dumps({"id": "one", "title": "Old", "lyrics": "Kom heim", "audio": "song.wav"}), encoding="utf-8")
            (sync / "timed_lyrics.json").write_text(json.dumps({"lines": [{"text": "Kom heim", "start": 0, "end": 1, "words": []}]}), encoding="utf-8")
            request = main.SongUpdateRequest(title="Old", description="", lyrics="Kom heim", english_translation="Come home", lyrics_language="is")
            with patch.object(main, "LIBRARY_ROOT", root):
                main.update_song("song-one", request)
            timed = json.loads((sync / "timed_lyrics.json").read_text(encoding="utf-8"))
        self.assertEqual("Come home", timed["lines"][0]["translation"])

    def test_editing_lyrics_invalidates_stale_timing(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "song-one"
            sync = folder / "lyrics_sync"
            sync.mkdir(parents=True)
            (folder / "song.json").write_text(json.dumps({"id": "one", "title": "Old", "lyrics": "old words", "lyrics_sync": {"status": "ready"}}), encoding="utf-8")
            (sync / "timed_lyrics.json").write_text(json.dumps({"lines": []}), encoding="utf-8")
            request = main.SongUpdateRequest(title="Old", description="", lyrics="new words", english_translation="", lyrics_language="en")
            with patch.object(main, "LIBRARY_ROOT", root):
                main.update_song("song-one", request)
            saved = json.loads((folder / "song.json").read_text(encoding="utf-8"))
        self.assertFalse(sync.exists())
        self.assertNotIn("lyrics_sync", saved)

    def test_song_folder_rejects_path_traversal(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            with patch.object(main, "LIBRARY_ROOT", Path(temp)):
                with self.assertRaises(HTTPException):
                    main.resolve_song_folder("../outside")

    def test_delete_song_removes_only_selected_folder(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            selected = root / "selected"
            untouched = root / "untouched"
            selected.mkdir(); untouched.mkdir()
            (selected / "song.wav").write_bytes(b"RIFF")
            with patch.object(main, "LIBRARY_ROOT", root):
                result = main.delete_song("selected")
            self.assertTrue(result["deleted"])
            self.assertFalse(selected.exists())
            self.assertTrue(untouched.exists())

    def test_delete_song_retries_a_temporarily_open_windows_file(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            selected = root / "selected"
            selected.mkdir()
            real_rmtree = main.shutil.rmtree
            attempts = 0

            def briefly_locked(path):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("file in use")
                return real_rmtree(path)

            with patch.object(main, "LIBRARY_ROOT", root), patch.object(main.shutil, "rmtree", side_effect=briefly_locked), patch.object(main.time, "sleep"):
                result = main.delete_song("selected")
            self.assertTrue(result["deleted"])
            self.assertEqual(3, attempts)

    def test_expected_windows_disconnect_is_not_a_job_failure(self) -> None:
        error = ConnectionResetError(10054, "remote host closed")
        error.winerror = 10054
        self.assertTrue(main.is_expected_windows_disconnect({
            "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
            "exception": error,
        }))

    def test_download_filename_uses_saved_song_title(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "song.json").write_text(json.dumps({"title": "Kom Heim"}), encoding="utf-8")
            self.assertEqual("Kom Heim.wav", main.download_filename(folder, ".wav"))

    def test_log_poll_resets_when_sidecar_ids_restart(self) -> None:
        latest = [{"id": 3, "ts": 1, "level": "INFO", "logger": "test", "message": "new process"}]
        with patch.object(main.ring, "snapshot", return_value=latest):
            result = main.logs(limit=10, since_id=900)
        self.assertTrue(result["reset"])
        self.assertEqual(latest, result["items"])

    def test_playlist_persists_song_membership_and_removal(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            library_root = root / "library"
            song_folder = library_root / "song-one"
            song_folder.mkdir(parents=True)
            (song_folder / "song.wav").write_bytes(b"RIFF")
            (song_folder / "song.json").write_text(
                json.dumps({"id": "one", "title": "One", "audio": "song.wav"}), encoding="utf-8"
            )
            playlists_file = root / "playlists.json"
            with patch.object(main, "LIBRARY_ROOT", library_root), patch.object(main, "PLAYLISTS_FILE", playlists_file):
                created = main.create_playlist(main.PlaylistCreateRequest(name="Road Songs"))["playlist"]
                main.add_song_to_playlist(created["id"], "one")
                self.assertEqual(["one"], main.load_playlists()[0]["song_ids"])
                main.remove_song_from_playlist(created["id"], "one")
                self.assertEqual([], main.load_playlists()[0]["song_ids"])
                main.delete_playlist(created["id"])
                self.assertEqual([], main.load_playlists())

    def test_workspace_is_exclusive_and_deleted_workspace_returns_songs_home(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            library_root = root / "library"
            song_folder = library_root / "song-one"
            song_folder.mkdir(parents=True)
            (song_folder / "song.wav").write_bytes(b"RIFF")
            (song_folder / "song.json").write_text(
                json.dumps({"id": "one", "title": "One", "audio": "song.wav"}), encoding="utf-8"
            )
            workspaces_file = root / "workspaces.json"
            with patch.object(main, "LIBRARY_ROOT", library_root), patch.object(main, "WORKSPACES_FILE", workspaces_file):
                initial = main.load_workspaces()
                self.assertEqual(["one"], initial[0]["song_ids"])
                created = main.create_workspace(main.PlaylistCreateRequest(name="Album Two"))["workspace"]
                main.move_song_to_workspace(created["id"], "one")
                moved = main.load_workspaces()
                self.assertEqual([], main.find_workspace(moved, "my-workspace")["song_ids"])
                self.assertEqual(["one"], main.find_workspace(moved, created["id"])["song_ids"])
                main.delete_workspace(created["id"])
                remaining = main.load_workspaces()
                self.assertEqual(["one"], main.find_workspace(remaining, "my-workspace")["song_ids"])

    def test_my_workspace_cannot_be_deleted(self) -> None:
        with self.assertRaises(HTTPException) as context:
            main.delete_workspace("my-workspace")
        self.assertEqual(409, context.exception.status_code)

    def test_video_studio_assets_and_routes_are_local(self) -> None:
        route_paths = {route.path for route in main.app.routes}
        self.assertIn("/video-studio", route_paths)
        self.assertIn("/api/video/render", route_paths)
        self.assertIn("/api/video/prepare", route_paths)
        script = (main.VIDEO_STUDIO_ROOT / "video_studio.js").read_text(encoding="utf-8")
        page = (main.VIDEO_STUDIO_ROOT / "index.html").read_text(encoding="utf-8")
        app = (PYTHON_ROOT.parent / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("yue2-video-studio-job", app)
        self.assertIn("videoStudioFrame", app)
        self.assertIn("/api/video/render", script)
        self.assertIn("/api/video/prepare", script)
        self.assertIn("ensureNoteSprites", script)
        self.assertIn("drawCachedNote", script)
        self.assertNotIn("backgroundVideo.currentTime = elements.audio.currentTime", script)
        self.assertIn("state.isRendering ? 32 : 14", script)
        self.assertIn("/api/library/${encodeURIComponent(songId)}/lyrics-sync", script)
        self.assertIn("yue2-video-studio-job", script)
        self.assertIn("releaseAudioForSync", script)
        self.assertIn("fetchJson", script)
        self.assertIn("Queued behind", script)
        self.assertIn("jobKindLabel", script)
        self.assertIn("Local Cover Art", page)
        self.assertIn('id="dual-on"', page)
        self.assertIn("attach_translations(payload", (PYTHON_ROOT / "main.py").read_text(encoding="utf-8"))
        self.assertIn("Both languages", page)
        self.assertIn("setDualLyrics", script)
        self.assertIn("lyricBlockHeight", script)
        self.assertIn("function vizFocus", script)
        self.assertIn("radius: 0", script)
        self.assertIn("state.centerImage", script)
        self.assertNotIn("ComfyUI Cover Art", page)
        self.assertNotIn("Style / Prompt", page)
        self.assertNotIn('id="track-summary"', page)
        self.assertIn('ctx.textAlign = "left"', script)
        self.assertIn('data-particle="warp"', page)
        self.assertIn('data-particle="notes"', page)
        self.assertNotIn('data-particle="confetti"', page)
        self.assertIn("drawBubble", script)
        self.assertIn("Math.cos(tilt) * speed", script)
        self.assertNotIn('data-particle="sparks"', page)
        self.assertIn('data-preset="sunburst"', page)
        self.assertIn('data-preset="arc"', page)
        self.assertIn('data-preset="split"', page)
        self.assertIn("drawSplitPreset", script)
        self.assertIn("lyricsAreCentered", script)
        self.assertIn('data-preset="scope"', page)
        self.assertIn('data-preset="mesh"', page)
        self.assertIn('data-preset="peak"', page)
        self.assertIn("drawScopePreset", script)
        self.assertIn("drawMeshPreset", script)
        self.assertIn("drawPeakPreset", script)
        self.assertIn("function vizFloor", script)
        self.assertIn("vizBottomRise", script)
        self.assertIn('data-preset="halo"', page)
        self.assertIn('data-preset="analog"', page)
        self.assertIn('data-preset="eq"', page)
        self.assertIn('data-preset="cascade"', page)
        self.assertIn('data-preset="stereo"', page)
        self.assertIn('data-preset="silk"', page)
        self.assertIn('data-preset="dots"', page)
        self.assertIn("rainbowColor", script)
        self.assertIn("eqBandColor", script)
        self.assertIn("WARM_COOL_STOPS", script)
        self.assertNotIn('data-preset="aurora"', page)
        self.assertNotIn('data-preset="skyline"', page)
        self.assertNotIn('data-preset="flow"', page)
        self.assertNotIn('data-preset="rings"', page)
        self.assertNotIn('data-preset="spiral"', page)
        self.assertNotIn('data-preset="helix"', page)
        self.assertNotIn('data-preset="vista"', page)
        self.assertNotIn('data-preset="contour"', page)
        self.assertNotIn('data-preset="disc"', page)
        self.assertNotIn('data-preset="ribbon"', page)
        self.assertNotIn("drawDiscPreset", script)
        self.assertNotIn("drawRibbonPreset", script)
        self.assertNotIn("drawAuroraPreset", script)
        self.assertNotIn("drawHelixPreset", script)
        self.assertNotIn("drawVistaPreset", script)
        self.assertIn('data-scene="chroma-green"', page)
        self.assertIn('data-scene="chroma-blue"', page)
        self.assertIn('data-scene="black"', page)
        self.assertNotIn('id="primary-color"', page)
        self.assertNotIn('id="secondary-color"', page)
        self.assertNotIn('data-preset="spectrum"', page)
        self.assertNotIn('data-preset="ring"', page)
        self.assertNotIn('data-preset="mirror"', page)
        self.assertIn("sampleBands", script)
        self.assertIn("drawArcPreset", script)
        self.assertNotIn("drawSpectrumPreset", script)
        self.assertNotIn("frequencyData.slice(0, 48)", script)
        self.assertIn("thin vertical streaks", script)
        self.assertIn("drawMusicNote", script)
        self.assertIn("setParticleStyle", script)
        self.assertIn('id="center-image-off"', page)
        self.assertIn("state.centerImage", script)
        self.assertIn("if (state.centerImage)", script)
        self.assertNotIn("particle.life -= 0.0022", script)
        self.assertIn("Fade by height, not a short timer.", script)
        self.assertNotIn("height - 80 - barHeight", script)
        self.assertIn("vizBottomRise(height, 0.28, 0.16)", script)
        self.assertIn("lastStartedLyricIndex", script)
        self.assertNotRegex(script, r"if \(currentIndex < 0\) \{\s*return 0;")

    def test_generate_preflight_allows_tauri_webview(self) -> None:
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        response = client.options("/api/generate", headers={
            "Origin": "https://tauri.localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
            "Access-Control-Request-Private-Network": "true",
        })
        self.assertIn(response.status_code, {200, 204})
        self.assertEqual(response.headers.get("access-control-allow-origin"), "https://tauri.localhost")
        self.assertEqual(response.headers.get("access-control-allow-private-network"), "true")

    def test_health_identifies_the_matching_desktop_protocol(self) -> None:
        payload = main.health()
        self.assertTrue(payload["ok"])
        self.assertEqual("YuE2 Studio", payload["service"])
        self.assertEqual(3, payload["protocol"])

    def test_desktop_retires_stale_sidecar_before_starting_its_own(self) -> None:
        source = (PYTHON_ROOT.parent / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        setup = source[source.index("if owns_sidecar {"):source.index("thread::spawn(move ||", source.index("if owns_sidecar {"))]
        self.assertIn("terminate_existing_sidecars();", setup)
        self.assertIn("wait_for_port_free", setup)
        self.assertIn("start_owned_sidecar", setup)
        self.assertNotIn("if already_listening()", setup)
        self.assertIn("payload.get(\"protocol\")", source)

    def test_desktop_watchdog_never_uses_http_timeout_to_restart_a_live_generation(self) -> None:
        source = (PYTHON_ROOT.parent / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        watchdog = source[source.index("thread::spawn(move ||", source.index("if owns_sidecar {")):source.index("            Ok(())", source.index("thread::spawn(move ||", source.index("if owns_sidecar {")))]
        self.assertIn("child.try_wait()", watchdog)
        self.assertIn("if child_running { continue; }", watchdog)
        self.assertNotIn("if sidecar_healthy()", watchdog)
        self.assertIn("start_owned_sidecar", watchdog)

    def test_video_studio_exposes_saved_timed_lyrics(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "song-one"
            sync = folder / "lyrics_sync"
            sync.mkdir(parents=True)
            (folder / "song.json").write_text(json.dumps({"id": "one", "title": "One"}), encoding="utf-8")
            payload = {"language": "en", "lines": [{"index": 1, "text": "Sing", "start": 0.2, "end": 1.0, "words": []}]}
            (sync / "timed_lyrics.json").write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(main, "LIBRARY_ROOT", root):
                loaded = main.get_timed_lyrics("song-one")
        self.assertEqual("Sing", loaded["lines"][0]["text"])
