from pathlib import Path
from getpass import getpass
import json
import os
import shutil
import subprocess
import tempfile
import time

from openai import OpenAI
from groq import Groq

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)


console = Console()


# ============================================================
# МОДЕЛІ
# ============================================================

GROQ_TRANSCRIBE_MODEL = "whisper-large-v3-turbo"
GROQ_TEXT_MODEL = "openai/gpt-oss-120b"

OPENAI_TRANSCRIBE_MODEL = "gpt-transcribe"
OPENAI_TRANSCRIBE_FALLBACK = "gpt-4o-transcribe"

OPENAI_TEXT_MODEL = "gpt-5.6-luna"


# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

# Максимальна тривалість фрагмента для моделей транскрипції.
CHUNK_MINUTES = 8


# ============================================================
# ПРОМПТ ДЛЯ КОНСПЕКТУ
# ============================================================

SUMMARY_PROMPT = """
Перетвори транскрипт заняття на зрозумілий конспект.

Вимоги:

- Збережи основний зміст заняття.
- Збережи важливі пояснення, теми та висновки.
- Не вигадуй інформацію, якої немає у транскрипті.
- Пиши простими і зрозумілими словами.
- Уникай надмірної технічної мови там, де вона не потрібна.
- Основний формат — кілька змістовних абзаців.
- Списки використовуй лише там, де вони справді покращують читабельність.
- Прибери зайві повтори, слова-паразити та несуттєві відступи.
- Назви програм, мов програмування, бібліотек, класів, методів
  та інших технічних понять зберігай.
- Відповідай українською мовою.

Транскрипт заняття:

"""


# ============================================================
# ВИБІР ПРОВАЙДЕРА
# ============================================================

def choose_provider():

    console.print(
        "\n[bold cyan]Оберіть API:[/bold cyan]"
    )

    console.print("1. OpenAI")
    console.print("2. GroqCloud")

    while True:

        choice = input(
            "\nВаш вибір: "
        ).strip()

        if choice == "1":
            return "openai"

        if choice == "2":
            return "groq"

        console.print(
            "[red]Введіть 1 або 2.[/red]"
        )


# ============================================================
# API KEY
# ============================================================

def get_api_key(provider):

    if provider == "openai":

        key = os.environ.get("OPENAI_API_KEY", "").strip()

        if not key:
            key = getpass(
                "Введіть OpenAI API Key: "
            )

        return key

    key = os.environ.get("GROQ_API_KEY", "").strip()

    if not key:
        key = getpass(
            "Введіть Groq API Key: "
        )

    return key


# ============================================================
# ШЛЯХ ДО АУДІО
# ============================================================

def get_audio_path():

    while True:

        path_text = input(
            "\nВкажіть шлях до аудіофайлу: "
        ).strip()

        path_text = (
            path_text
            .strip('"')
            .strip("'")
        )

        path = Path(
            path_text
        )

        if (
            path.exists()
            and path.is_file()
        ):
            return path

        console.print(
            "[red]"
            "Файл не знайдено. "
            "Спробуйте ще раз."
            "[/red]"
        )


# ============================================================
# ЗБЕРЕЖЕННЯ ТЕКСТУ
# ============================================================

def save_text(
    path: Path,
    text: str
):

    path.write_text(
        text,
        encoding="utf-8"
    )


# ============================================================
# ПЕРЕВІРКА FFMPEG
# ============================================================

def check_ffmpeg():

    ffmpeg_path = shutil.which(
        "ffmpeg"
    )

    if ffmpeg_path is None:

        console.print(
            "\n[bold red]"
            "FFmpeg не знайдено."
            "[/bold red]"
        )

        console.print(
            "Встановіть FFmpeg "
            "і додайте його в PATH."
        )

        return False

    return True


# ============================================================
# НАРІЗАННЯ АУДІО
# ============================================================

def split_audio(
    audio_path: Path,
    chunk_minutes: int = CHUNK_MINUTES
):

    chunk_seconds = (
        chunk_minutes * 60
    )

    # Створюємо тимчасову папку
    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="audio_chunks_"
        )
    )

    output_pattern = (
        temp_dir /
        "chunk_%03d.mp3"
    )

    console.print(
        f"\n[cyan]"
        f"Нарізаю аудіо на фрагменти "
        f"по {chunk_minutes} хв..."
        f"[/cyan]"
    )

    command = [
        "ffmpeg",

        "-hide_banner",
        "-loglevel",
        "error",

        "-i",
        str(audio_path),

        "-f",
        "segment",

        "-segment_time",
        str(chunk_seconds),

        "-reset_timestamps",
        "1",

        # Перекодовуємо в MP3
        "-codec:a",
        "libmp3lame",

        # Нормальна якість,
        # але без зайво великого розміру
        "-q:a",
        "4",

        str(output_pattern)
    ]

    try:

        subprocess.run(
            command,
            check=True
        )

    except subprocess.CalledProcessError:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        raise RuntimeError(
            "FFmpeg не зміг "
            "нарізати аудіофайл."
        )

    chunks = sorted(
        temp_dir.glob(
            "chunk_*.mp3"
        )
    )

    if not chunks:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        raise RuntimeError(
            "Не вдалося створити "
            "фрагменти аудіо."
        )

    console.print(
        f"[green]"
        f"Створено фрагментів: "
        f"{len(chunks)}"
        f"[/green]"
    )

    return chunks, temp_dir


# ============================================================
# GROQ — ТРАНСКРИПЦІЯ
# ============================================================

def transcribe_groq(
    client,
    audio_path
):

    console.print(
        f"\n[bold]"
        f"Транскрипція через Groq: "
        f"[/bold]"
        f"{GROQ_TRANSCRIBE_MODEL}"
    )

    chunks, temp_dir = split_audio(
        audio_path,
        CHUNK_MINUTES
    )

    full_transcript = []

    raw_results = []

    try:

        with Progress(

            SpinnerColumn(),

            TextColumn(
                "[progress.description]"
                "{task.description}"
            ),

            BarColumn(),

            TaskProgressColumn(),

            TimeElapsedColumn(),

            console=console,

        ) as progress:

            task = progress.add_task(
                "Підготовка...",
                total=len(chunks)
            )

            for index, chunk_path in enumerate(
                chunks,
                start=1
            ):

                progress.update(
                    task,
                    description=(
                        f"Фрагмент "
                        f"{index}/{len(chunks)}"
                    )
                )

                with open(
                    chunk_path,
                    "rb"
                ) as audio_file:

                    result = (
                        client
                        .audio
                        .transcriptions
                        .create(
                            file=(
                                chunk_path.name,
                                audio_file.read()
                            ),

                            model=(
                                GROQ_TRANSCRIBE_MODEL
                            ),

                            response_format=(
                                "verbose_json"
                            ),

                            language="uk",

                            temperature=0.0,
                        )
                    )

                text = (
                    result.text
                    .strip()
                )

                full_transcript.append(
                    text
                )

                raw_results.append(
                    result
                )

                progress.advance(
                    task
                )

    finally:

        # Видаляємо тимчасові MP3
        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

    transcript = "\n\n".join(
        full_transcript
    )

    console.print(
        "\n[green]"
        "Транскрипцію завершено."
        "[/green]"
    )

    return transcript, raw_results


# ============================================================
# OPENAI — ТРАНСКРИПЦІЯ
# ============================================================

def transcribe_openai(
    client,
    audio_path
):

    console.print(
        f"\n[bold]"
        f"Транскрипція через OpenAI: "
        f"[/bold]"
        f"{OPENAI_TRANSCRIBE_MODEL}"
    )

    with Progress(

        SpinnerColumn(),

        TextColumn(
            "[progress.description]"
            "{task.description}"
        ),

        TimeElapsedColumn(),

        console=console,

    ) as progress:

        task = progress.add_task(
            "OpenAI транскрибує аудіо...",
            total=None
        )

        try:

            with open(
                audio_path,
                "rb"
            ) as audio_file:

                result = (
                    client
                    .audio
                    .transcriptions
                    .create(
                        model=(
                            OPENAI_TRANSCRIBE_MODEL
                        ),

                        file=audio_file,
                    )
                )

        except Exception as error:

            console.print(
                "\n[yellow]"
                f"{OPENAI_TRANSCRIBE_MODEL} "
                f"не спрацювала."
                "[/yellow]"
            )

            console.print(
                "[yellow]"
                f"Пробую fallback: "
                f"{OPENAI_TRANSCRIBE_FALLBACK}"
                "[/yellow]"
            )

            with open(
                audio_path,
                "rb"
            ) as audio_file:

                result = (
                    client
                    .audio
                    .transcriptions
                    .create(
                        model=(
                            OPENAI_TRANSCRIBE_FALLBACK
                        ),

                        file=audio_file,
                    )
                )

        progress.update(
            task,
            description=(
                "Транскрипція завершена."
            )
        )

    return result.text, result


# ============================================================
# GROQ — КОНСПЕКТ
# ============================================================

def summarize_groq(
    client,
    transcript
):

    console.print(
        f"\n[bold]"
        f"Створення конспекту: "
        f"[/bold]"
        f"{GROQ_TEXT_MODEL}\n"
    )

    full_prompt = (
        SUMMARY_PROMPT
        + transcript
    )

    stream = (
        client
        .chat
        .completions
        .create(

            model=GROQ_TEXT_MODEL,

            messages=[
                {
                    "role": "user",
                    "content": full_prompt,
                }
            ],

            stream=True,
        )
    )

    summary = ""

    generated_chars = 0

    last_update = time.time()

    console.print(
        "[cyan]Генерація конспекту...[/cyan]"
    )

    for chunk in stream:

        delta = (
            chunk
            .choices[0]
            .delta
            .content
        )

        if delta:

            summary += delta

            generated_chars += len(
                delta
            )

            if (
                time.time()
                - last_update
                > 0.15
            ):

                console.print(
                    f"\r"
                    f"[cyan]"
                    f"Згенеровано: "
                    f"{generated_chars:,} "
                    f"символів"
                    f"[/cyan]",
                    end=""
                )

                last_update = (
                    time.time()
                )

    console.print(
        f"\r"
        f"[green]"
        f"Готово: "
        f"{generated_chars:,} "
        f"символів"
        f"[/green]         "
    )

    return summary


# ============================================================
# OPENAI — КОНСПЕКТ
# ============================================================

def summarize_openai(
    client,
    transcript
):

    console.print(
        f"\n[bold]"
        f"Створення конспекту: "
        f"[/bold]"
        f"{OPENAI_TEXT_MODEL}\n"
    )

    full_prompt = (
        SUMMARY_PROMPT
        + transcript
    )

    summary = ""

    generated_chars = 0

    last_update = time.time()

    console.print(
        "[cyan]"
        "Генерація конспекту..."
        "[/cyan]"
    )

    with client.responses.stream(

        model=OPENAI_TEXT_MODEL,

        input=full_prompt,

    ) as stream:

        for event in stream:

            if (
                event.type
                ==
                "response.output_text.delta"
            ):

                text = event.delta

                summary += text

                generated_chars += len(
                    text
                )

                if (
                    time.time()
                    - last_update
                    > 0.15
                ):

                    console.print(
                        f"\r"
                        f"[cyan]"
                        f"Згенеровано: "
                        f"{generated_chars:,} "
                        f"символів"
                        f"[/cyan]",
                        end=""
                    )

                    last_update = (
                        time.time()
                    )

    console.print(
        f"\r"
        f"[green]"
        f"Готово: "
        f"{generated_chars:,} "
        f"символів"
        f"[/green]        "
    )

    return summary


# ============================================================
# ЗБЕРЕЖЕННЯ GROQ JSON
# ============================================================

def save_groq_json(
    raw_results,
    json_path
):

    raw_json = []

    for result in raw_results:

        if hasattr(
            result,
            "model_dump"
        ):

            raw_json.append(
                result.model_dump()
            )

        else:

            raw_json.append(
                result
            )

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            raw_json,
            file,
            ensure_ascii=False,
            indent=2,
            default=str
        )


# ============================================================
# MAIN
# ============================================================

def main():

    console.print(
        "\n[bold magenta]"
        "=== Транскрипція "
        "та конспект заняття ==="
        "[/bold magenta]"
    )

    provider = choose_provider()

    api_key = get_api_key(
        provider
    )

    audio_path = get_audio_path()

    console.print(
        f"\n[green]"
        f"Файл: "
        f"[/green]"
        f"{audio_path}"
    )

    output_directory = (
        audio_path.parent
    )

    base_name = (
        audio_path.stem
    )

    transcript_path = (
        output_directory
        /
        f"{base_name}_transcript.txt"
    )

    summary_path = (
        output_directory
        /
        f"{base_name}_summary.txt"
    )

    json_path = (
        output_directory
        /
        f"{base_name}_transcript.json"
    )

    # ========================================================
    # OPENAI
    # ========================================================

    if provider == "openai":

        client = OpenAI(
            api_key=api_key
        )

        transcript, raw_result = (
            transcribe_openai(
                client,
                audio_path
            )
        )

        save_text(
            transcript_path,
            transcript
        )

        console.print(
            f"\n[green]"
            f"Транскрипт збережено:"
            f"[/green]\n"
            f"{transcript_path}"
        )

        summary = (
            summarize_openai(
                client,
                transcript
            )
        )

    # ========================================================
    # GROQ
    # ========================================================

    else:

        if not check_ffmpeg():
            return

        client = Groq(
            api_key=api_key
        )

        transcript, raw_results = (
            transcribe_groq(
                client,
                audio_path
            )
        )

        save_text(
            transcript_path,
            transcript
        )

        console.print(
            f"\n[green]"
            f"Транскрипт збережено:"
            f"[/green]\n"
            f"{transcript_path}"
        )

        try:

            save_groq_json(
                raw_results,
                json_path
            )

            console.print(
                f"\n[green]"
                f"JSON збережено:"
                f"[/green]\n"
                f"{json_path}"
            )

        except Exception as error:

            console.print(
                "\n[yellow]"
                "Не вдалося зберегти JSON."
                "[/yellow]"
            )

            console.print(
                f"[dim]{error}[/dim]"
            )

        summary = (
            summarize_groq(
                client,
                transcript
            )
        )

    # ========================================================
    # ЗБЕРІГАЄМО КОНСПЕКТ
    # ========================================================

    save_text(
        summary_path,
        summary
    )

    console.print(
        "\n\n[bold green]"
        "=== ОБРОБКУ ЗАВЕРШЕНО ==="
        "[/bold green]"
    )

    console.print(
        f"\nТранскрипт:\n"
        f"{transcript_path}"
    )

    console.print(
        f"\nКонспект:\n"
        f"{summary_path}"
    )


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    main()
