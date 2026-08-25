"""Multi-Format Export Engine (JSON, TXT, Markdown, HTML, PDF)."""
import json
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional, Union
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from app.models.schemas import PipelineResult


def format_seconds(seconds: float) -> str:
    """Formats float seconds into MM:SS string."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def export_json(result: PipelineResult) -> str:
    """Exports complete machine-readable pipeline result."""
    return result.model_dump_json(indent=2)


def export_txt(result: PipelineResult) -> str:
    """Exports plain text formatted report."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"HINDI AUDIO INTELLIGENCE REPORT — JOB: {result.job_id}")
    lines.append("=" * 70)
    lines.append("")

    if result.audio_metadata:
        lines.append(f"File: {result.audio_metadata.original_filename}")
        lines.append(f"Duration: {format_seconds(result.audio_metadata.duration_seconds)} ({result.audio_metadata.duration_seconds}s)")
        lines.append(f"Speakers: {len(result.speakers)}")
        lines.append("")

    if result.summary:
        lines.append("--- EXECUTIVE SUMMARY ---")
        lines.append(result.summary.high_level_summary)
        lines.append("")
        if result.summary.key_takeaways:
            lines.append("Key Takeaways:")
            for k in result.summary.key_takeaways:
                lines.append(f"• {k}")
            lines.append("")

    lines.append("--- TRANSCRIPT (SPEAKER ATTRIBUTED) ---")
    for seg in result.transcript:
        lines.append(f"[{format_seconds(seg.start)}–{format_seconds(seg.end)}] {seg.speaker}: {seg.text}")
    lines.append("")

    if result.claims:
        lines.append("--- SUBSTANTIVE CLAIMS ---")
        for c in result.claims:
            lines.append(f"• [{format_seconds(c.source_start)}] {c.speaker}: {c.claim_text}")
        lines.append("")

    if result.contradictions:
        lines.append("--- POTENTIAL CONTRADICTIONS ---")
        for cntr in result.contradictions:
            lines.append(f"• {cntr.speaker}: \"{cntr.earlier_statement}\" ({format_seconds(cntr.earlier_timestamp)}) vs \"{cntr.later_statement}\" ({format_seconds(cntr.later_timestamp)})")
            lines.append(f"  Note: {cntr.explanation}")
        lines.append("")

    return "\n".join(lines)


def export_markdown(result: PipelineResult) -> str:
    """Exports structured GitHub Flavored Markdown report."""
    md = []
    md.append(f"# Audio Intelligence Report: `{result.job_id}`\n")

    if result.audio_metadata:
        md.append("## Audio Properties")
        md.append(f"- **Filename:** `{result.audio_metadata.original_filename}`")
        md.append(f"- **Duration:** {format_seconds(result.audio_metadata.duration_seconds)} ({result.audio_metadata.duration_seconds:.1f}s)")
        md.append(f"- **Sample Rate:** {result.audio_metadata.sample_rate} Hz | **Channels:** {result.audio_metadata.channels}")
        md.append("")

    if result.summary:
        md.append("## Executive Summary")
        md.append(f"> {result.summary.high_level_summary}\n")
        if result.summary.detailed_summary:
            md.append(result.summary.detailed_summary)
            md.append("")
        if result.summary.key_takeaways:
            md.append("### Key Takeaways")
            for t in result.summary.key_takeaways:
                md.append(f"- {t}")
            md.append("")

    if result.speakers:
        md.append("## Speaker Participation")
        md.append("| Speaker | Speech Time (s) | Share (%) | Turns |")
        md.append("| :--- | :--- | :--- | :--- |")
        for spk in result.speakers:
            md.append(f"| **{spk.speaker_id}** | {spk.total_speech_time}s | {spk.percentage_of_conversation}% | {spk.segment_count} |")
        md.append("")

    md.append("## Transcript")
    md.append("| Timestamp | Speaker | Spoken Utterance (Devanagari / Hinglish) | Confidence |")
    md.append("| :--- | :--- | :--- | :--- |")
    for seg in result.transcript:
        conf_str = f"{int(seg.confidence * 100)}%" if seg.confidence else "N/A"
        md.append(f"| `{format_seconds(seg.start)}` | **{seg.speaker}** | {seg.text} | {conf_str} |")
    md.append("")

    if result.claims:
        md.append("## Substantive Claims & Evidence")
        for c in result.claims:
            md.append(f"- **[{format_seconds(c.source_start)}] {c.speaker}:** {c.claim_text}")
            md.append(f"  *Evidence:* *\"{c.evidence_quote}\"*")
        md.append("")

    if result.contradictions:
        md.append("## Potential Contradictions")
        for cntr in result.contradictions:
            md.append(f"> [!NOTE]\n> **Speaker:** `{cntr.speaker}`\n> Earlier (`{format_seconds(cntr.earlier_timestamp)}`): \"{cntr.earlier_statement}\"\n> Later (`{format_seconds(cntr.later_timestamp)}`): \"{cntr.later_statement}\"\n> *{cntr.explanation}*")
            md.append("")

    return "\n".join(md)


def export_html(result: PipelineResult) -> str:
    """Exports self-contained responsive HTML report."""
    md_content = export_markdown(result)
    # Simple HTML generator with clean modern typography
    transcript_rows = "".join([
        f"<tr><td><code>{format_seconds(s.start)}</code></td><td><span class='badge'>{s.speaker}</span></td><td>{s.text}</td><td>{int((s.confidence or 0.8)*100)}%</td></tr>"
        for s in result.transcript
    ])
    
    claims_list = "".join([
        f"<li><strong>[{format_seconds(c.source_start)}] {c.speaker}:</strong> {c.claim_text}<br><small>Evidence: <em>\"{c.evidence_quote}\"</em></small></li>"
        for c in result.claims
    ])

    return f"""<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <title>Audio Intelligence Report - {result.job_id}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; color: #1e293b; max-width: 900px; margin: 0 auto; padding: 2rem; }}
        h1, h2, h3 {{ color: #0f172a; }}
        .header {{ border-bottom: 2px solid #e2e8f0; padding-bottom: 1rem; margin-bottom: 2rem; }}
        .badge {{ background: #e0e7ff; color: #3730a3; padding: 2px 8px; border-radius: 4px; font-size: 0.85rem; font-weight: 600; }}
        table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
        th, td {{ padding: 8px 12px; border-bottom: 1px solid #e2e8f0; text-align: left; }}
        th {{ background: #f8fafc; }}
        .summary-box {{ background: #f1f5f9; border-left: 4px solid #3b82f6; padding: 1rem; border-radius: 0 8px 8px 0; margin-bottom: 1.5rem; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Hindi Audio Intelligence Report</h1>
        <p><strong>Job ID:</strong> <code>{result.job_id}</code> | <strong>File:</strong> {result.audio_metadata.original_filename if result.audio_metadata else 'N/A'}</p>
    </div>

    <div class="summary-box">
        <h3>Executive Summary</h3>
        <p>{result.summary.high_level_summary if result.summary else 'Analysis complete.'}</p>
    </div>

    <h2>Speaker-Attributed Transcript</h2>
    <table>
        <thead><tr><th>Time</th><th>Speaker</th><th>Utterance</th><th>Confidence</th></tr></thead>
        <tbody>{transcript_rows}</tbody>
    </table>

    <h2>Claims & Evidence</h2>
    <ul>{claims_list or '<li>No substantive claims recorded.</li>'}</ul>
</body>
</html>"""


def export_pdf(result: PipelineResult, output_path: Union[Path, str]) -> bytes:
    """Generates styled PDF document using ReportLab."""
    output_path = Path(output_path)
    buffer = BytesIO()
    doc = SimpleDocTemplate(str(output_path) if str(output_path) else buffer, pagesize=letter)
    styles = getSampleStyleSheet()

    story = []
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1e3a8a")
    )
    story.append(Paragraph(f"Hindi Audio Intelligence Report", title_style))
    story.append(Spacer(1, 10))

    info_text = f"<b>Job ID:</b> {result.job_id} | <b>File:</b> {result.audio_metadata.original_filename if result.audio_metadata else 'N/A'}"
    story.append(Paragraph(info_text, styles["Normal"]))
    story.append(Spacer(1, 15))

    if result.summary:
        story.append(Paragraph("<b>Executive Summary:</b>", styles["Heading2"]))
        story.append(Paragraph(result.summary.high_level_summary, styles["Normal"]))
        story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Speaker-Attributed Transcript:</b>", styles["Heading2"]))
    table_data = [["Time", "Speaker", "Utterance"]]
    for seg in result.transcript[:30]:  # Cap at 30 segments for PDF layout
        table_data.append([
            format_seconds(seg.start),
            seg.speaker,
            seg.text[:70] + ("..." if len(seg.text) > 70 else "")
        ])

    t = Table(table_data, colWidths=[60, 90, 360])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(t)

    doc.build(story)
    if output_path.exists():
        return output_path.read_bytes()
    return buffer.getvalue()


def export_pipeline_result(
    result: PipelineResult,
    export_format: Literal["json", "txt", "md", "html", "pdf"],
    output_path: Optional[Path | str] = None
) -> Union[str, bytes]:
    """Universal dispatcher for exporting reports in requested format."""
    if export_format == "json":
        content = export_json(result)
    elif export_format == "txt":
        content = export_txt(result)
    elif export_format == "md":
        content = export_markdown(result)
    elif export_format == "html":
        content = export_html(result)
    elif export_format == "pdf":
        out = output_path or "report.pdf"
        return export_pdf(result, out)
    else:
        raise ValueError(f"Unsupported format: {export_format}")

    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
    return content
