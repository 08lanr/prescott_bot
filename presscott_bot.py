"""
Presscott Discord Bot
Queries eFlow affiliate API by sub1 (campid) via /presscott subid:xx
"""

import discord
from discord import app_commands
import aiohttp
import os
from datetime import datetime, timezone

# ─── CONFIG ────────────────────────────────────────────────
DISCORD_TOKEN   = os.environ.get("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
EFLOW_API_KEY   = os.environ.get("EFLOW_API_KEY", "YOUR_EFLOW_API_KEY")
EFLOW_URL       = "https://api.eflow.team/v1/affiliates/reporting/entity"
TIMEZONE_ID     = 90   # change if your network uses a different tz
# ────────────────────────────────────────────────────────────

intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)


def build_payload(subid: str, from_date: str, to_date: str) -> dict:
    return {
        "timezone_id": TIMEZONE_ID,
        "currency_id": "USD",
        "from": from_date,
        "to":   to_date,
        "columns": [
            {"column": "sub1"},
            {"column": "offer"},
        ],
        "query": {
            "filters": [
                {
                    "filter_id_value": subid,
                    "resource_type":   "sub1"
                }
            ],
            "exclusions":     [],
            "metric_filters": [],
            "user_metrics":   [],
            "settings":       {}
        }
    }


async def fetch_eflow(subid: str, from_date: str, to_date: str) -> dict:
    payload = build_payload(subid, from_date, to_date)
    headers = {
        "Content-Type":  "application/json",
        "x-eflow-api-key": EFLOW_API_KEY
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(EFLOW_URL, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()


def parse_results(data, subid: str) -> discord.Embed:
    # Handle both list and dict response formats
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("table", {}).get("rows", []) or data.get("rows", []) or []
    else:
        rows = []

    # Aggregate across all rows matching this subid
    total_revenue     = 0.0
    total_conversions = 0
    total_clicks      = 0
    offers_seen       = set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        cols      = row.get("columns", []) or []
        reporting = row.get("reporting", {}) or {}

        # Grab offer name if present
        if isinstance(cols, list):
            for col in cols:
                if isinstance(col, dict) and col.get("column") == "offer":
                    offers_seen.add(col.get("label", "Unknown"))

        total_revenue     += float(reporting.get("revenue",     0))
        total_conversions += int(reporting.get("conversions",   0))
        total_clicks      += int(reporting.get("total_clicks",  0))

    color = discord.Color.green() if total_revenue > 0 else discord.Color.orange()

    embed = discord.Embed(
        title  = f"📊 Sub-ID Report: `{subid}`",
        color  = color,
        timestamp = datetime.now(timezone.utc)
    )

    embed.add_field(name="💰 Revenue",     value=f"${total_revenue:,.2f}", inline=True)
    embed.add_field(name="✅ Conversions", value=str(total_conversions),   inline=True)
    embed.add_field(name="👆 Clicks",      value=str(total_clicks),        inline=True)

    if offers_seen:
        embed.add_field(
            name  = "🎯 Offer(s)",
            value = "\n".join(offers_seen),
            inline = False
        )

    if not rows:
        embed.description = "⚠️ No data found for this sub-ID in the selected date range."

    embed.set_footer(text="Presscott · eFlow Data")
    return embed


# ─── SLASH COMMAND ─────────────────────────────────────────
@tree.command(name="presscott", description="Query revenue for a sub-ID (campid)")
@app_commands.describe(
    subid      = "The campid / sub1 to look up (e.g. RLTEST1)",
    from_date  = "Start date YYYY-MM-DD (default: today)",
    to_date    = "End date   YYYY-MM-DD (default: today)"
)
async def presscott(
    interaction: discord.Interaction,
    subid:      str,
    from_date:  str = None,
    to_date:    str = None
):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from_date = from_date or today
    to_date   = to_date   or today

    await interaction.response.defer(thinking=True)   # show "Bot is thinking…"

    try:
        data  = await fetch_eflow(subid.strip(), from_date, to_date)
        embed = parse_results(data, subid.strip())
        embed.add_field(
            name  = "📅 Date Range",
            value = f"{from_date} → {to_date}",
            inline = False
        )
        await interaction.followup.send(embed=embed)

    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(
            f"❌ eFlow API error `{e.status}`: {e.message}", ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Unexpected error: `{e}`", ephemeral=True
        )


# ─── STARTUP ───────────────────────────────────────────────
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user} — slash commands synced.")


client.run(DISCORD_TOKEN)
