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


def get_date_range(preset: str):
    today = datetime.now(timezone.utc)
    if preset == "today":
        return today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif preset == "yesterday":
        d = today - timedelta(days=1)
        return d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d")
    elif preset == "7days":
        return (today - timedelta(days=7)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif preset == "30days":
        return (today - timedelta(days=30)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:
        return (today - timedelta(days=7)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


async def fetch_eflow(from_date: str, to_date: str, subid: str = None):
    filters = []
    if subid:
        filters = [{"filter_id_value": subid, "resource_type": "sub1"}]

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
            "filters":        filters,
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


def build_embed(data: dict, subid: str, from_date: str, to_date: str) -> discord.Embed:
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
    return embed


# ─── DATE RANGE SELECT MENU ────────────────────────────────
class DateRangeSelect(discord.ui.Select):
    def __init__(self, subid: str):
        self.subid = subid
        options = [
            discord.SelectOption(label="Today",       value="today",   emoji="📅"),
            discord.SelectOption(label="Yesterday",   value="yesterday", emoji="🕐"),
            discord.SelectOption(label="Last 7 Days", value="7days",   emoji="📆", default=True),
            discord.SelectOption(label="Last 30 Days",value="30days",  emoji="🗓️"),
        ]
        super().__init__(placeholder="📅 Change date range...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        from_date, to_date = get_date_range(self.values[0])
        data  = await fetch_eflow(from_date, to_date, self.subid)
        embed = build_embed(data, self.subid, from_date, to_date)
        await interaction.message.edit(embed=embed)


class DateRangeView(discord.ui.View):
    def __init__(self, subid: str):
        super().__init__(timeout=300)
        self.add_item(DateRangeSelect(subid))


# ─── /presscott COMMAND ────────────────────────────────────
@tree.command(name="presscott", description="Query revenue for a sub-ID")
@app_commands.describe(subid="The campid to look up e.g. RLGRAVY2")
async def presscott(interaction: discord.Interaction, subid: str):
    await interaction.response.defer(thinking=True)
    try:
        from_date, to_date = get_date_range("7days")
        data  = await fetch_eflow(from_date, to_date, subid.strip())
        embed = build_embed(data, subid.strip(), from_date, to_date)
        view  = DateRangeView(subid.strip())
        await interaction.followup.send(embed=embed, view=view)
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(f"❌ eFlow API error `{e.status}`: {e.message}")
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected error: `{e}`")


# ─── /camps COMMAND ────────────────────────────────────────
@tree.command(name="camps", description="List all campids with clicks and revenue")
@app_commands.describe(range="Date range: today, yesterday, 7days, 30days")
@app_commands.choices(range=[
    app_commands.Choice(name="Today",        value="today"),
    app_commands.Choice(name="Yesterday",    value="yesterday"),
    app_commands.Choice(name="Last 7 Days",  value="7days"),
    app_commands.Choice(name="Last 30 Days", value="30days"),
])
async def camps(interaction: discord.Interaction, range: str = "7days"):
    await interaction.response.defer(thinking=True)
    try:
        from_date, to_date = get_date_range(range)
        data = await fetch_eflow(from_date, to_date)

        rows = data.get("table", {}).get("rows", []) if isinstance(data, dict) else []

        if not rows:
            # Fall back to summary only
            summary = data.get("summary", {}) if isinstance(data, dict) else {}
            revenue = float(summary.get("revenue", 0))
            clicks  = int(summary.get("total_click", 0))

            embed = discord.Embed(
                title     = "📋 All Camps Overview",
                color     = discord.Color.green() if revenue > 0 else discord.Color.orange(),
                timestamp = datetime.now(timezone.utc)
            )
            embed.add_field(name="💰 Total Revenue", value=f"${revenue:,.2f}", inline=True)
            embed.add_field(name="👆 Total Clicks",  value=str(clicks),        inline=True)
            embed.add_field(name="📅 Date Range",    value=f"{from_date} → {to_date}", inline=False)
            embed.set_footer(text="Presscott · eFlow Data")
            await interaction.followup.send(embed=embed)
            return

        # Build per-camp list
        lines = []
        for row in rows:
            cols      = row.get("columns", [])
            reporting = row.get("reporting", {})
            sub1      = next((c.get("label", "unknown") for c in cols if c.get("column") == "sub1"), "unknown")
            revenue   = float(reporting.get("revenue", 0))
            clicks    = int(reporting.get("total_click", 0))

            if revenue > 0:
                lines.append(f"✅ `{sub1}` — ${revenue:,.2f} | {clicks} clicks")
            else:
                lines.append(f"⬜ `{sub1}` — No Revenue | {clicks} clicks")

        embed = discord.Embed(
            title       = "📋 All Camps",
            description = "\n".join(lines) if lines else "No data found.",
            color       = discord.Color.blurple(),
            timestamp   = datetime.now(timezone.utc)
        )
        embed.add_field(name="📅 Date Range", value=f"{from_date} → {to_date}", inline=False)
        embed.set_footer(text="Presscott · eFlow Data")
        await interaction.followup.send(embed=embed)

    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(f"❌ eFlow API error `{e.status}`: {e.message}")
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected error: `{e}`")


# ─── STARTUP ───────────────────────────────────────────────
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user} — slash commands synced.")


client.run(DISCORD_TOKEN)
