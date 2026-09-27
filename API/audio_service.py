"""Обробка аудіозапису та створення конспекту через серверні API-ключі."""

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AudioPipelineError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


class AudioSummaryService:
    MAX_UPLOAD_BYTES = 300 * 1024 * 1024
    MAX_CHUNK_BYTES = 24 * 1024 * 1024
    MAX_CHUNK_SECONDS = 8 * 60
    TARGET_CHUNK_SECONDS = MAX_CHUNK_SECONDS - 1
    READ_SIZE = 1024 * 1024
    API_TIMEOUT_SECONDS = 240

    AUDIO_EXTENSIONS = {
        ".flac",
        ".m4a",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpga",
        ".ogg",
        ".wav",
        ".webm",
    }

    TRANSCRIBERS = {
        "openai": {
            "key_name": "OPENAI_API_KEY",
            "url": "https://api.openai.com/v1/audio/transcriptions",
            "model": "whisper-1",
        },
        "groq": {
            "key_name": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/audio/transcriptions",
            "model": "whisper-large-v3-turbo",
        },
    }

    SUMMARIZERS = {
        "openai-gpt-5.6-luna": {
            "provider": "openai",
            "key_name": "OPENAI_API_KEY",
            "url": "https://api.openai.com/v1/responses",
            "model": "gpt-5.6-luna",
        },
        "groq-gpt-oss-120b": {
            "provider": "groq",
            "key_name": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": "openai/gpt-oss-120b",
        },
        "groq-gpt-oss-20b": {
            "provider": "groq",
            "key_name": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": "openai/gpt-oss-20b",
        },
    }

    SUMMARY_INSTRUCTIONS = """Створи зрозумілий конспект заняття українською мовою.

Збережи головні теми, пояснення, приклади та висновки з транскрипту.
Не додавай фактів, яких немає в записі. Прибери повтори й слова-паразити.
Залишай точні назви програм, мов, бібліотек, класів і методів.
Використовуй просте форматування: короткий заголовок, змістовні підзаголовки
та короткі марковані списки там, де вони полегшують читання. Не додавай вступ
про те, що це зробив штучний інтелект."""

    def process_upload(
        self,
        source,
        content_length,
        extension,
        transcription_provider,
        summary_model,
    ):
        extension = (extension or "").strip().lower()
        if not extension.startswith("."):
            extension = "." + extension
        if extension not in self.AUDIO_EXTENSIONS:
            raise AudioPipelineError(415, "Цей формат аудіофайлу не підтримується.")
        if not 0 < content_length <= self.MAX_UPLOAD_BYTES:
            raise AudioPipelineError(413, "Файл має бути розміром до 300 МБ.")

        transcriber = self.TRANSCRIBERS.get(transcription_provider)
        summarizer = self.SUMMARIZERS.get(summary_model)
        if transcriber is None or summarizer is None:
            raise AudioPipelineError(400, "Перевір обрані сервіси та моделі.")

        transcription_key = self._required_key(transcriber["key_name"])
        summary_key = self._required_key(summarizer["key_name"])
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise AudioPipelineError(
                503,
                "Для обробки аудіо потрібні FFmpeg і ffprobe у PATH. "
                "Установи FFmpeg та перезапусти сервер.",
            )

        with tempfile.TemporaryDirectory(prefix="lesson_audio_") as temporary:
            work_dir = Path(temporary)
            audio_path = work_dir / ("recording" + extension)
            self._save_upload(source, content_length, audio_path)
            chunks = self._split_audio(audio_path, work_dir / "chunks", ffmpeg, ffprobe)

            transcript_parts = []
            for chunk_path in chunks:
                transcript_parts.append(
                    self._transcribe_chunk(
                        chunk_path,
                        transcription_provider,
                        transcriber,
                        transcription_key,
                    )
                )

            transcript = "\n\n".join(part for part in transcript_parts if part.strip())
            if not transcript:
                raise AudioPipelineError(502, "Сервіс не повернув текст розпізнавання.")

            summary = self._summarize(transcript, summarizer, summary_key)
            return {"summary": summary, "chunks": len(chunks)}

    @staticmethod
    def _required_key(key_name):
        key = os.environ.get(key_name, "").strip()
        if not key:
            raise AudioPipelineError(
                503,
                f"На сервері не налаштовано {key_name}. Додай ключ як змінну середовища та перезапусти сервер.",
            )
        return key

    def _save_upload(self, source, content_length, target):
        remaining = content_length
        try:
            with target.open("wb") as destination:
                while remaining:
                    block = source.read(min(self.READ_SIZE, remaining))
                    if not block:
                        raise AudioPipelineError(400, "Передавання аудіофайлу перервалося.")
                    destination.write(block)
                    remaining -= len(block)
        except OSError:
            raise AudioPipelineError(500, "Не вдалося тимчасово зберегти аудіофайл на сервері.")

    def _split_audio(self, audio_path, output_dir, ffmpeg, ffprobe):
        output_dir.mkdir()
        output_pattern = output_dir / "chunk_%03d.mp3"
        command = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-map",
            "0:a:0",
            "-vn",
            "-f",
            "segment",
            "-segment_time",
            str(self.TARGET_CHUNK_SECONDS),
            "-reset_timestamps",
            "1",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "96k",
            "-codec:a",
            "libmp3lame",
            str(output_pattern),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=900)
        except FileNotFoundError:
            raise AudioPipelineError(503, "Не знайдено FFmpeg. Установи FFmpeg та перезапусти сервер.")
        except subprocess.TimeoutExpired:
            raise AudioPipelineError(422, "FFmpeg не встиг обробити запис за 15 хвилин.")
        except subprocess.CalledProcessError:
            raise AudioPipelineError(422, "Не вдалося прочитати аудіофайл або створити фрагменти.")

        chunks = sorted(output_dir.glob("chunk_*.mp3"))
        if not chunks:
            raise AudioPipelineError(422, "У вибраному файлі не знайдено аудіодоріжку.")

        for chunk in chunks:
            if chunk.stat().st_size > self.MAX_CHUNK_BYTES:
                raise AudioPipelineError(
                    413,
                    "Один фрагмент завеликий для API. Спробуй файл із нижчою якістю запису.",
                )
            self._check_chunk_duration(chunk, ffprobe)
        return chunks

    def _check_chunk_duration(self, chunk, ffprobe):
        command = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(chunk),
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
            duration = float(json.loads(result.stdout)["format"]["duration"])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, KeyError, json.JSONDecodeError):
            raise AudioPipelineError(422, "Не вдалося перевірити тривалість фрагмента аудіо.")
        if duration > self.MAX_CHUNK_SECONDS:
            raise AudioPipelineError(422, "Фрагмент аудіо перевищив обмеження у 8 хвилин.")

    def _transcribe_chunk(self, chunk, provider, configuration, api_key):
        fields = {
            "model": configuration["model"],
            "language": "uk",
            "response_format": "json",
            "temperature": "0",
        }
        response = self._post_multipart(
            configuration["url"],
            api_key,
            fields,
            chunk,
            "audio/mpeg",
            provider,
        )
        try:
            text = response["text"].strip()
        except (KeyError, AttributeError):
            raise AudioPipelineError(502, "Сервіс розпізнавання повернув неочікувану відповідь.")
        return text

    def _summarize(self, transcript, configuration, api_key):
        if configuration["provider"] == "groq":
            payload = {
                "model": configuration["model"],
                "messages": [
                    {"role": "system", "content": self.SUMMARY_INSTRUCTIONS},
                    {"role": "user", "content": "Транскрипт заняття:\n\n" + transcript},
                ],
            }
        else:
            payload = {
                "model": configuration["model"],
                "instructions": self.SUMMARY_INSTRUCTIONS,
                "input": "Транскрипт заняття:\n\n" + transcript,
            }
        response = self._post_json(configuration["url"], api_key, payload, "модель конспекту")

        if configuration["provider"] == "groq":
            try:
                summary = response["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                summary = ""
        else:
            summary = response.get("output_text", "")
            if not summary:
                pieces = []
                for item in response.get("output", []):
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            pieces.append(content.get("text", ""))
                summary = "\n".join(pieces)

        summary = summary.strip() if isinstance(summary, str) else ""
        if not summary:
            raise AudioPipelineError(502, "Модель не повернула текст конспекту.")
        return summary

    def _post_multipart(self, url, api_key, fields, file_path, content_type, provider):
        boundary = uuid.uuid4().hex
        body_parts = []
        for name, value in fields.items():
            body_parts.extend(
                [
                    ("--" + boundary + "\r\n").encode("ascii"),
                    (f'Content-Disposition: form-data; name="{name}"\r\n\r\n').encode("ascii"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        body_parts.extend(
            [
                ("--" + boundary + "\r\n").encode("ascii"),
                (
                    'Content-Disposition: form-data; name="file"; filename="'
                    + file_path.name
                    + '"\r\n'
                ).encode("ascii"),
                ("Content-Type: " + content_type + "\r\n\r\n").encode("ascii"),
                file_path.read_bytes(),
                b"\r\n",
                ("--" + boundary + "--\r\n").encode("ascii"),
            ]
        )
        request = Request(
            url,
            data=b"".join(body_parts),
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "multipart/form-data; boundary=" + boundary,
            },
            method="POST",
        )
        return self._send_request(request, provider)

    def _post_json(self, url, api_key, payload, provider):
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._send_request(request, provider)

    def _send_request(self, request, provider):
        try:
            with urlopen(request, timeout=self.API_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            key_name = "OPENAI_API_KEY" if provider == "openai" else "GROQ_API_KEY"
            if error.code in (401, 403):
                message = f"{provider} не прийняв ключ. Перевір {key_name} на сервері."
            elif error.code == 429:
                message = f"{provider} повідомив про ліміт або недостатній баланс API."
            else:
                message = f"Помилка API {provider} (HTTP {error.code}). Перевір доступність вибраної моделі."
            raise AudioPipelineError(502, message)
        except (URLError, TimeoutError, OSError):
            raise AudioPipelineError(502, f"Не вдалося з’єднатися з API {provider}.")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AudioPipelineError(502, f"API {provider} повернув неочікувану відповідь.")
