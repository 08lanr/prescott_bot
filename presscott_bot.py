import discord
from discord import app_commands
import aiohttp
import os
from datetime import datetime, timezone

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


@tree.command(name="presscott", description="Query revenue for a sub-ID")
@app_commands.describe(subid="The campid to look up e.g. RLGRAVY2")
async def presscott(interaction: discord.Interaction, subid: str):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await interaction.response.defer(thinking=True)

    try:
        data = await fetch_eflow(subid.strip(), today, today)
        # Show raw response so we can see the structure
        raw = str(data)[:1800]
        await interaction.followup.send(f"**Raw API response:**\n```\n{raw}\n```")

    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(f"❌ eFlow API error `{e.status}`: {e.message}")
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected error: `{e}`")


@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user} — slash commands synced.")


client.run(DISCORD_TOKEN)
