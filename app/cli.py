"""Command Line Interface (CLI) for Hindi Audio Intelligence Pipeline."""
import argparse
import sys
import uuid
from pathlib import Path
from rich.console import Console
from rich.table import Table
from app.config.settings import settings
from app.pipeline.orchestrator import AudioIntelligencePipeline
from app.reporting.export import export_pipeline_result

console = Console()


def run_cli():
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="Analyze Hindi and Hinglish audio recordings with local intelligence pipeline."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Process an audio recording")
    analyze_parser.add_argument("audio_file", type=str, help="Path to input audio file (WAV, MP3, M4A, etc.)")
    analyze_parser.add_argument("--device", type=str, choices=["auto", "cpu", "cuda"], default="auto", help="Inference device")
    analyze_parser.add_argument("--output", "-o", type=str, default=None, help="Output destination file")
    analyze_parser.add_argument("--format", "-f", type=str, choices=["json", "txt", "md", "html", "pdf"], default="json", help="Output format")
    analyze_parser.add_argument("--language", "-l", type=str, default="hi", help="Audio language code (default: hi)")
    analyze_parser.add_argument("--model", "-m", type=str, default="small", choices=["tiny", "base", "small", "medium", "large-v3"], help="ASR model size")

    # info command
    subparsers.add_parser("info", help="Display environment and model configuration")

    # server command
    server_parser = subparsers.add_parser("serve", help="Start the FastAPI backend server")
    server_parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address")
    server_parser.add_argument("--port", type=int, default=8000, help="Port number")

    args = parser.parse_args()

    if args.command == "info" or not args.command:
        console.print("[bold green]Hindi Audio Intelligence Pipeline[/bold green]")
        console.print(f"[cyan]Device:[/cyan] {settings.get_effective_device()} (Compute: {settings.get_compute_type()})")
        console.print(f"[cyan]ASR Model:[/cyan] faster-whisper ({settings.ASR_MODEL_SIZE})")
        console.print(f"[cyan]VAD:[/cyan] Silero VAD (v6.2)")
        console.print(f"[cyan]Diarization:[/cyan] {settings.DIARIZATION_ENGINE}")
        console.print(f"[cyan]LLM Provider:[/cyan] {settings.LLM_PROVIDER}")
        return

    if args.command == "serve":
        import uvicorn
        console.print(f"[bold cyan]Starting API server on http://{args.host}:{args.port}...[/bold cyan]")
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
        return

    if args.command == "analyze":
        audio_path = Path(args.audio_file)
        if not audio_path.exists():
            console.print(f"[bold red]Error:[/bold red] File '{args.audio_file}' not found.")
            sys.exit(1)

        # Apply CLI overrides to settings
        settings.MODEL_DEVICE = args.device
        settings.ASR_MODEL_SIZE = args.model

        job_id = f"cli_{uuid.uuid4().hex[:8]}"
        console.print(f"[bold green]Starting Analysis for:[/bold green] {audio_path.name} (Job: {job_id})")

        pipeline = AudioIntelligencePipeline()

        with console.status("[bold yellow]Processing audio through pipeline...[/bold yellow]") as status:
            def on_progress(pct: int, stage: str):
                status.update(f"[bold yellow]({pct}%) Stage: {stage}[/bold yellow]")

            result = pipeline.process_job(
                job_id=job_id,
                audio_path=audio_path,
                progress_callback=on_progress,
                language=args.language
            )

        console.print(f"[bold green]✓ Processing Complete![/bold green] (Duration: {result.metadata.processing_duration_sec}s, RTF: {result.metadata.real_time_factor})")

        # Display Summary Table
        table = Table(title="Speaker-Attributed Transcript")
        table.add_column("Time", justify="center", style="cyan")
        table.add_column("Speaker", justify="center", style="magenta")
        table.add_column("Utterance", style="white")
        table.add_column("Confidence", justify="right", style="green")

        for seg in result.transcript:
            conf_str = f"{int((seg.confidence or 0.8)*100)}%"
            table.add_row(f"{seg.start:.1f}s - {seg.end:.1f}s", seg.speaker, seg.text, conf_str)
        console.print(table)

        # Claims
        if result.claims:
            console.print("\n[bold yellow]Substantive Claims & Evidence:[/bold yellow]")
            for c in result.claims:
                console.print(f"• [[cyan]{c.source_start:.1f}s[/cyan]] [magenta]{c.speaker}[/magenta]: {c.claim_text}")

        # Contradictions
        if result.contradictions:
            console.print("\n[bold red]Potential Contradictions Detected:[/bold red]")
            for cntr in result.contradictions:
                console.print(f"• [magenta]{cntr.speaker}[/magenta]: {cntr.explanation}")

        # Save or Output
        out_fmt = args.format
        out_path = args.output or f"{audio_path.stem}_analysis.{out_fmt}"
        content = export_pipeline_result(result, export_format=out_fmt, output_path=out_path)

        if not args.output:
            console.print(f"\n[bold green]Report saved to:[/bold green] {out_path}")


if __name__ == "__main__":
    run_cli()
