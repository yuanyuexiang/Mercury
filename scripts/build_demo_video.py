"""Build a self-contained Mercury marketing demo video.

The generated video uses only fictional UI data and requires ffmpeg plus macOS `say`.
It is deliberately independent of the live demo environment so it can be rebuilt safely.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "demo-video" / "build"
OUTPUT = ROOT / "demo-video" / "mercury-demo-live-16x9.mp4"
SRT = ROOT / "demo-video" / "mercury-demo-live-en.srt"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"


@dataclass(frozen=True)
class Scene:
    title: str
    narration: str
    body: str
    kind: str


SCENES = [
    Scene(
        "A buyer. 3:07 AM.",
        "A potential buyer messages your business on Telegram while your team is asleep.",
        "No one on your team is online.",
        "hook",
    ),
    Scene(
        "Answers from approved documents",
        "Mercury answers from your approved product documents, including deployment, pricing, and delivery details.",
        "Can you deploy this for our own Telegram bot?|Yes. Each customer gets a dedicated instance and database.|How much is the pilot, and how soon can it go live?|The pilot is scoped after a short review. Delivery can start in seven days.",
        "chat",
    ),
    Scene(
        "No invented promises",
        "If the answer is not in your materials, it does not invent one.",
        "Pricing · Contracts · Refunds · Security|Unsupported claims are refused or handed to a person.",
        "guardrail",
    ),
    Scene(
        "Qualifies the buyer naturally",
        "As the conversation continues, it captures the company, requirement, budget, and timeline, without forcing the buyer through a long form.",
        "We're a 50-person SaaS company. We need HubSpot and want a demo next week. Budget is around $1,000.|50-person team|HubSpot|$1,000 budget|Demo next week",
        "qualify",
    ),
    Scene(
        "A sensitive question reaches the right person",
        "Here is the real Mercury workspace. Julia asks about an N D A and a data processing agreement. Mercury escalates the question and pauses the AI.",
        "handoff-conversation.png",
        "capture",
    ),
    Scene(
        "A pipeline, not another chat inbox",
        "The dashboard shows conversations becoming leads, high intent opportunities, synced records, and wins. Your team starts with what deserves attention.",
        "dashboard.png",
        "capture",
    ),
    Scene(
        "Every score is explainable",
        "Open a lead and you see the company, need, budget, timeline, scoring reasons, and full conversation. This one reached one hundred and ten points and became a customer.",
        "lead-detail.png",
        "capture",
    ),
    Scene(
        "Know exactly where serious buyers came from",
        "Every campaign link carries its source into Mercury, so you can compare conversations, leads, and high intent buyers by channel.",
        "promotion.png",
        "capture",
    ),
    Scene(
        "Telegram conversations → qualified leads",
        "Mercury turns Telegram conversations into qualified sales leads, automatically, with a human always in control.",
        "Answer · Qualify · Score · Hand off",
        "summary",
    ),
    Scene(
        "7-day Telegram Lead Pilot",
        "Talk to the bot and try the workflow yourself. Apply for a seven-day paid pilot.",
        "Talk to the bot.|The demo is the product.|Limited paid pilot · Scope confirmed after a short review",
        "cta",
    ),
]


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def base(content: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#07111f"/><stop offset="1" stop-color="#10233d"/></linearGradient>
  <linearGradient id="accent" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#38bdf8"/><stop offset="1" stop-color="#6366f1"/></linearGradient>
  <filter id="shadow"><feDropShadow dx="0" dy="18" stdDeviation="22" flood-opacity=".28"/></filter>
</defs>
<rect width="1920" height="1080" fill="url(#bg)"/>
<circle cx="1740" cy="100" r="320" fill="#2563eb" opacity=".09"/><circle cx="120" cy="1020" r="360" fill="#06b6d4" opacity=".07"/>
<g font-family="Arial, sans-serif">{content}</g>
<g transform="translate(90 970)"><circle cx="24" cy="24" r="24" fill="url(#accent)"/><path d="M12 31 L24 10 L36 31 L29 28 L24 38 L19 28 Z" fill="white"/><text x="62" y="34" fill="#dbeafe" font-size="30" font-weight="700">MERCURY</text></g>
</svg>'''


def heading(title: str, kicker: str = "TELEGRAM LEAD CONVERSION") -> str:
    return f'<text x="90" y="105" fill="#38bdf8" font-size="24" font-weight="700" letter-spacing="3">{esc(kicker)}</text><text x="90" y="180" fill="white" font-size="58" font-weight="700">{esc(title)}</text>'


def phone(messages: list[tuple[str, str]], status: str = "online") -> str:
    parts = [
        '<g transform="translate(1110 80)" filter="url(#shadow)"><rect width="650" height="900" rx="54" fill="#0b1524" stroke="#334155" stroke-width="4"/>',
        '<rect x="22" y="22" width="606" height="856" rx="38" fill="#eaf3f8"/>',
        '<rect x="22" y="22" width="606" height="106" rx="38" fill="#172b4d"/><circle cx="82" cy="75" r="32" fill="url(#accent)"/>',
        '<text x="130" y="69" fill="white" font-size="27" font-weight="700">Mercury Assistant</text>',
        f'<text x="130" y="99" fill="#7dd3fc" font-size="19">{esc(status)}</text>',
    ]
    y = 165
    for who, text in messages:
        is_user = who == "user"
        x = 185 if is_user else 48
        width = 390 if len(text) < 60 else 500
        if is_user:
            x = 606 - width - 28
        lines = wrap(text, 42 if width > 450 else 32)
        height = 40 + 29 * len(lines)
        fill = "#d9fdd3" if is_user else "white"
        parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="20" fill="{fill}"/>')
        for i, line in enumerate(lines):
            parts.append(f'<text x="{x + 20}" y="{y + 35 + i * 29}" fill="#172033" font-size="21">{esc(line)}</text>')
        y += height + 22
    parts.append('</g>')
    return "".join(parts)


def wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) > width and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def render(scene: Scene) -> str:
    if scene.kind == "hook":
        return base(f'<text x="960" y="450" text-anchor="middle" fill="#38bdf8" font-size="28" font-weight="700" letter-spacing="4">A TELEGRAM INQUIRY</text><text x="960" y="550" text-anchor="middle" fill="white" font-size="82" font-weight="700">{esc(scene.title)}</text><text x="960" y="625" text-anchor="middle" fill="#94a3b8" font-size="34">{esc(scene.body)}</text>')
    if scene.kind == "chat":
        items = scene.body.split("|")
        content = heading(scene.title) + '<text x="90" y="245" fill="#94a3b8" font-size="29">A real customer conversation, handled instantly.</text>'
        content += phone([("user", items[0]), ("bot", items[1]), ("user", items[2]), ("bot", items[3])])
        content += '<g transform="translate(90 355)"><rect width="850" height="265" rx="30" fill="#0f2139" stroke="#1e3a5f"/><text x="42" y="65" fill="#7dd3fc" font-size="23" font-weight="700">KNOWLEDGE SOURCE</text><text x="42" y="125" fill="white" font-size="32">Product docs · Pricing · FAQ</text><text x="42" y="185" fill="#94a3b8" font-size="25">Every answer stays grounded in approved material.</text></g>'
        return base(content)
    if scene.kind == "guardrail":
        tags, desc = scene.body.split("|")
        content = heading(scene.title, "BUILT-IN GUARDRAILS")
        for i, tag in enumerate(tags.split(" · ")):
            x = 90 + (i % 2) * 470
            y = 305 + (i // 2) * 150
            content += f'<rect x="{x}" y="{y}" width="420" height="105" rx="22" fill="#132944" stroke="#334e70"/><text x="{x+35}" y="{y+65}" fill="white" font-size="31" font-weight="700">{esc(tag)}</text>'
        content += f'<g transform="translate(1080 285)"><circle cx="310" cy="230" r="210" fill="#0b2138" stroke="#38bdf8" stroke-width="5"/><path d="M310 95 L450 150 V270 C450 370 382 423 310 454 C238 423 170 370 170 270 V150 Z" fill="#0ea5e9" opacity=".22" stroke="#7dd3fc" stroke-width="5"/><path d="M236 270 L290 324 L394 214" fill="none" stroke="white" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/></g><text x="90" y="720" fill="#cbd5e1" font-size="33">{esc(desc)}</text>'
        return base(content)
    if scene.kind == "qualify":
        items = scene.body.split("|")
        content = heading(scene.title)
        content += phone([("user", items[0])])
        content += '<g transform="translate(90 290)"><rect width="850" height="510" rx="32" fill="#0f2139" stroke="#1e3a5f"/>'
        for i, tag in enumerate(items[1:]):
            y = 75 + i * 100
            content += f'<circle cx="62" cy="{y-8}" r="22" fill="#22c55e"/><path d="M51 {y-8} l8 8 l16 -19" fill="none" stroke="white" stroke-width="6"/><text x="108" y="{y}" fill="white" font-size="32" font-weight="700">{esc(tag)}</text>'
        return base(content + '</g>')
    if scene.kind == "handoff":
        items = scene.body.split("|")
        content = heading(scene.title, "SAFE HUMAN HANDOFF")
        content += phone([("user", items[0]), ("bot", items[1])], "human operator notified")
        content += f'<g transform="translate(90 330)"><rect width="780" height="255" rx="30" fill="#321828" stroke="#fb7185" stroke-width="3"/><circle cx="95" cy="95" r="45" fill="#e11d48"/><text x="95" y="111" text-anchor="middle" fill="white" font-size="42" font-weight="700">!</text><text x="170" y="83" fill="#fda4af" font-size="24" font-weight="700">CONVERSATION STATUS</text><text x="170" y="140" fill="white" font-size="40" font-weight="700">{esc(items[2])}</text><text x="55" y="210" fill="#fecdd3" font-size="27">The AI will not reply until the operator restores it.</text></g>'
        return base(content)
    if scene.kind == "lead":
        items = scene.body.split("|")
        content = heading(scene.title, "SALES WORKSPACE")
        content += '<g transform="translate(90 250)" filter="url(#shadow)"><rect width="1740" height="650" rx="28" fill="#f8fafc"/><rect width="1740" height="88" rx="28" fill="#ffffff"/><text x="42" y="57" fill="#172033" font-size="30" font-weight="700">Lead detail</text><rect x="1320" y="24" width="355" height="48" rx="24" fill="#fee2e2"/><text x="1498" y="57" text-anchor="middle" fill="#dc2626" font-size="25" font-weight="700">{}</text><text x="55" y="160" fill="#172033" font-size="42" font-weight="700">{}</text><text x="55" y="205" fill="#64748b" font-size="27">{}</text><text x="55" y="282" fill="#64748b" font-size="21" font-weight="700">QUALIFICATION</text>'.format(esc(items[2]), esc(items[0]), esc(items[1]))
        for i, reason in enumerate(items[3:]):
            y = 340 + i * 58
            content += f'<text x="70" y="{y}" fill="#334155" font-size="27">✓ {esc(reason)}</text>'
        content += '<rect x="840" y="145" width="830" height="430" rx="22" fill="#eef6ff"/><text x="885" y="205" fill="#1d4ed8" font-size="23" font-weight="700">CONVERSATION SUMMARY</text><text x="885" y="270" fill="#172033" font-size="29">50-person SaaS team evaluating a pilot.</text><text x="885" y="320" fill="#172033" font-size="29">Needs HubSpot integration.</text><text x="885" y="370" fill="#172033" font-size="29">Budget: $1,000 · Timeline: next week.</text><rect x="885" y="430" width="300" height="70" rx="18" fill="#2563eb"/><text x="1035" y="475" text-anchor="middle" fill="white" font-size="26" font-weight="700">Take over chat</text></g>'
        return base(content)
    if scene.kind == "channels":
        cells = scene.body.split("|")
        rows = [cells[i:i+4] for i in range(0, len(cells), 4)]
        content = heading(scene.title, "CHANNEL ATTRIBUTION") + '<g transform="translate(170 285)" filter="url(#shadow)"><rect width="1580" height="520" rx="30" fill="#f8fafc"/>'
        widths = [560, 320, 280, 320]
        xs = [0, 560, 880, 1160]
        for ri, row in enumerate(rows):
            y = ri * 104
            fill = "#eaf2ff" if ri == 0 else ("#ffffff" if ri % 2 else "#f1f5f9")
            content += f'<rect y="{y}" width="1580" height="104" fill="{fill}" rx="{30 if ri == 0 else 0}"/>'
            for ci, cell in enumerate(row):
                anchor = "start" if ci == 0 else "middle"
                x = xs[ci] + (35 if ci == 0 else widths[ci] / 2)
                color = "#1d4ed8" if ri == 0 else ("#dc2626" if ci == 3 and ri > 0 else "#172033")
                content += f'<text x="{x}" y="{y+65}" text-anchor="{anchor}" fill="{color}" font-size="28" font-weight="{700 if ri == 0 or ci == 3 else 400}">{esc(cell)}</text>'
        return base(content + '</g>')
    if scene.kind == "summary":
        content = f'<text x="960" y="250" text-anchor="middle" fill="#38bdf8" font-size="25" font-weight="700" letter-spacing="4">MERCURY</text><text x="960" y="390" text-anchor="middle" fill="white" font-size="66" font-weight="700">Telegram conversations</text><text x="960" y="480" text-anchor="middle" fill="#7dd3fc" font-size="66" font-weight="700">→ qualified sales leads</text>'
        for i, item in enumerate(scene.body.split(" · ")):
            x = 300 + i * 440
            content += f'<circle cx="{x}" cy="650" r="58" fill="url(#accent)"/><text x="{x}" y="662" text-anchor="middle" fill="white" font-size="32" font-weight="700">{i+1}</text><text x="{x}" y="755" text-anchor="middle" fill="#dbeafe" font-size="28" font-weight="700">{esc(item)}</text>'
        return base(content)
    items = scene.body.split("|")
    return base(f'<text x="960" y="285" text-anchor="middle" fill="#38bdf8" font-size="27" font-weight="700" letter-spacing="4">MERCURY PILOT</text><text x="960" y="420" text-anchor="middle" fill="white" font-size="76" font-weight="700">{esc(scene.title)}</text><rect x="680" y="500" width="560" height="90" rx="45" fill="url(#accent)"/><text x="960" y="557" text-anchor="middle" fill="white" font-size="30" font-weight="700">{esc(items[0])}</text><text x="960" y="670" text-anchor="middle" fill="#dbeafe" font-size="36" font-weight="700">{esc(items[1])}</text><text x="960" y="742" text-anchor="middle" fill="#94a3b8" font-size="24">{esc(items[2])}</text>')


def timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def main() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("say") or not shutil.which("magick"):
        raise SystemExit("This builder requires ffmpeg, ImageMagick, and the macOS say command")
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    clips: list[Path] = []
    subtitles: list[str] = []
    elapsed = 0.0
    for index, scene in enumerate(SCENES, 1):
        stem = BUILD / f"scene-{index:02}"
        svg = stem.with_suffix(".svg")
        png = stem.with_suffix(".png")
        aiff = stem.with_suffix(".aiff")
        wav = stem.with_suffix(".wav")
        clip = stem.with_suffix(".mp4")
        if scene.kind == "capture":
            shutil.copy2(ROOT / "demo-video" / "captures" / scene.body, png)
        else:
            svg.write_text(render(scene), encoding="utf-8")
            run("magick", "-font", FONT, "-background", "none", str(svg), str(png))
        run("say", "-v", "Samantha", "-r", "176", "-o", str(aiff), scene.narration)
        run("ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), "-ar", "48000", "-ac", "2", str(wav))
        with wave.open(str(wav), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate() + 0.8
        fade_out = max(0.5, duration - 0.4)
        run(
            "ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", str(png), "-i", str(wav),
            "-filter_complex", f"[0:v]scale=1920:1080,zoompan=z='min(zoom+0.00010,1.02)':d=1:s=1920x1080:fps=30,fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out:.3f}:d=0.4[v];[1:a]apad=pad_dur=1,afade=t=in:st=0:d=0.15,afade=t=out:st={fade_out:.3f}:d=0.3[a]",
            "-map", "[v]", "-map", "[a]", "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "medium",
            "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(clip),
        )
        clips.append(clip)
        subtitles.append(f"{index}\n{timestamp(elapsed)} --> {timestamp(elapsed + duration)}\n{scene.narration}\n")
        elapsed += duration

    concat = BUILD / "concat.txt"
    concat.write_text("".join(f"file '{clip.name}'\n" for clip in clips), encoding="utf-8")
    run("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(OUTPUT))
    SRT.write_text("\n".join(subtitles), encoding="utf-8")
    print(f"Built {OUTPUT} ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
