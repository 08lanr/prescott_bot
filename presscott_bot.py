import discord
from discord import app_commands
import aiohttp
import os
from datetime import datetime, timezone, timedelta

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
EFLOW_API_KEY = os.environ.get("EFLOW_API_KEY", "YOUR_EFLOW_API_KEY")
EFLOW_URL     = "https://api.eflow.team/v1/affiliates/reporting/entity"
TIMEZONE_ID   = 90

intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)


async def fetch_eflow(subid: str, from_date: str, to_date: str):
    payload = {
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
                {"filter_id_value": subid, "resource_type": "sub1"}
            ],
            "exclusions":     [],
            "metric_filters": [],
            "user_metrics":   [],
            "settings":       {}
        }
    }
    headers = {
        "Content-Type":    "application/json",
        "x-eflow-api-key": EFLOW_API_KEY
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(EFLOW_URL, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)


@tree.command(name="presscott", description="Query revenue for a sub-ID (defaults to last 7 days)")
@app_commands.describe(
    subid     = "The campid to look up e.g. RLGRAVY2",
    from_date = "Start date YYYY-MM-DD (default: 7 days ago)",
    to_date   = "End date YYYY-MM-DD (default: today)"
)
async def presscott(
    interaction: discord.Interaction,
    subid:      str,
    from_date:  str = None,
    to_date:    str = None
):
    today     = datetime.now(timezone.utc)
    to_date   = to_date   or today.strftime("%Y-%m-%d")
    from_date = from_date or (today - timedelta(days=7)).strftime("%Y-%m-%d")

    await interaction.response.defer(thinking=True)

    try:
        data    = await fetch_eflow(subid.strip(), from_date, to_date)
        summary = data.get("summary", {})

        revenue     = float(summary.get("revenue", 0))
        clicks      = int(summary.get("total_click", 0))
        conversions = int(summary.get("cv", 0))
        events      = int(summary.get("event", 0))

        color = discord.Color.green() if revenue > 0 else discord.Color.orange()

        embed = discord.Embed(
            title     = f"📊 Sub-ID Report: `{subid}`",
            color     = color,
            timestamp = datetime.now(timezone.utc)
        )
        embed.add_field(name="💰 Revenue",     value=f"${revenue:,.2f}", inline=True)
        embed.add_field(name="✅ Conversions", value=str(conversions),   inline=True)
        embed.add_field(name="👆 Clicks",      value=str(clicks),        inline=True)
        embed.add_field(name="⚡ Events",      value=str(events),        inline=True)
        embed.add_field(name="📅 Date Range",  value=f"{from_date} → {to_date}", inline=False)
        embed.set_footer(text="Presscott · eFlow Data")

        await interaction.followup.send(embed=embed)

    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(f"❌ eFlow API error `{e.status}`: {e.message}")
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected error: `{e}`")


@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user} — slash commands synced.")


client.run(DISCORD_TOKEN)
