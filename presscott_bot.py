import discord
from discord import app_commands
import aiohttp
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
EFLOW_API_KEY = os.environ.get("EFLOW_API_KEY", "YOUR_EFLOW_API_KEY")
EFLOW_URL     = "https://api.eflow.team/v1/affiliates/reporting/entity"
TIMEZONE_ID   = 90

# Dates are computed in this zone, not UTC
REPORT_TZ = ZoneInfo("America/Los_Angeles")

intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)


def get_date_range(preset: str):
    today = datetime.now(REPORT_TZ)
    if preset == "today":
        return today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    if preset == "yesterday":
        d = today - timedelta(days=1)
        return d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d")
    if preset == "30days":
        return (today - timedelta(days=30)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    return (today - timedelta(days=7)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


async def fetch_eflow(from_date: str, to_date: str, subid: str):
    payload = {
        "timezone_id": TIMEZONE_ID,
        "currency_id": "USD",
        "from": from_date,
        "to":   to_date,
        "columns": [{"column": "sub1"}],
        "query": {
            "filters":        [{"filter_id_value": subid, "resource_type": "sub1"}],
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


def build_embed(data, subid, from_date, to_date):
    s = data.get("summary", {}) if isinstance(data, dict) else {}

    revenue     = float(s.get("revenue", 0) or 0)
    clicks      = int(s.get("total_click", 0) or 0)
    conversions = int(s.get("cv", 0) or 0)
    events      = int(s.get("event", 0) or 0)

    embed = discord.Embed(
        title     = f"📊 Sub-ID Report: `{subid}`",
        color     = discord.Color.green() if revenue > 0 else discord.Color.orange(),
        timestamp = datetime.now(timezone.utc)
    )
    embed.add_field(name="💰 Revenue",     value=f"${revenue:,.2f}", inline=True)
    embed.add_field(name="✅ Conversions", value=str(conversions),   inline=True)
    embed.add_field(name="👆 Clicks",      value=str(clicks),        inline=True)
    embed.add_field(name="⚡ Events",      value=str(events),        inline=True)
    embed.add_field(name="📅 Date Range",  value=f"{from_date} → {to_date}", inline=False)
    embed.set_footer(text="Presscott · eFlow Data")
    return embed


class DateRangeSelect(discord.ui.Select):
    def __init__(self, subid):
        self.subid = subid
        super().__init__(
            placeholder="📅 Change date range...",
            options=[
                discord.SelectOption(label="Today",        value="today",     emoji="📅"),
                discord.SelectOption(label="Yesterday",    value="yesterday", emoji="🕐"),
                discord.SelectOption(label="Last 7 Days",  value="7days",     emoji="📆", default=True),
                discord.SelectOption(label="Last 30 Days", value="30days",    emoji="🗓️"),
            ]
        )

    async def callback(self, interaction):
        await interaction.response.defer()
        f, t = get_date_range(self.values[0])
        try:
            data = await fetch_eflow(f, t, self.subid)
            await interaction.message.edit(embed=build_embed(data, self.subid, f, t))
        except Exception as e:
            await interaction.followup.send(
                f"❌ `{type(e).__name__}: {e}`", ephemeral=True
            )


class DateRangeView(discord.ui.View):
    def __init__(self, subid):
        super().__init__(timeout=600)
        self.add_item(DateRangeSelect(subid))


@tree.command(name="presscott", description="Query revenue for a sub-ID")
@app_commands.describe(subid="The campid to look up e.g. RLGRAVY2")
async def presscott(interaction: discord.Interaction, subid: str):
    await interaction.response.defer(thinking=True)
    sub = subid.strip()
    try:
        f, t = get_date_range("7days")
        data = await fetch_eflow(f, t, sub)
        await interaction.followup.send(
            embed=build_embed(data, sub, f, t),
            view=DateRangeView(sub)
        )
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(f"❌ eFlow API error `{e.status}`: {e.message}")
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected error: `{type(e).__name__}: {e}`")


@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user} — slash commands synced.")


client.run(DISCORD_TOKEN)
