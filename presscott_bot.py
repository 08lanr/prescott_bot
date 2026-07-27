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
    if preset == "yesterday":
        d = today - timedelta(days=1)
        return d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d")
    if preset == "30days":
        return (today - timedelta(days=30)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    # default: 7 days
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
        "columns": [{"column": "sub1"}],
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


def safe_get(obj, key, default=None):
    """Only call .get() when obj is actually a dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def extract_summary(data):
    return safe_get(data, "summary", {}) or {}


def extract_rows(data):
    """Everflow may return table as a list OR a dict with rows. Handle both."""
    if isinstance(data, list):
        return data

    table = safe_get(data, "table")
    if isinstance(table, list):
        return table
    if isinstance(table, dict):
        rows = table.get("rows")
        if isinstance(rows, list):
            return rows

    rows = safe_get(data, "rows")
    if isinstance(rows, list):
        return rows

    return []


def row_label(row):
    """Pull the sub1 value out of a row, whatever key Everflow used."""
    cols = safe_get(row, "columns", []) or []
    if isinstance(cols, list):
        for c in cols:
            if not isinstance(c, dict):
                continue
            ctype = c.get("column_type") or c.get("column")
            if ctype == "sub1":
                return c.get("label") or c.get("id") or "unknown"
        # no sub1 column matched — use the first label we find
        for c in cols:
            if isinstance(c, dict) and (c.get("label") or c.get("id")):
                return c.get("label") or c.get("id")
    return "unknown"


def build_embed(data, subid, from_date, to_date):
    s           = extract_summary(data)
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


# ─── DATE RANGE DROPDOWN ───────────────────────────────────
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
        f, t  = get_date_range(self.values[0])
        data  = await fetch_eflow(f, t, self.subid)
        await interaction.message.edit(embed=build_embed(data, self.subid, f, t))


class DateRangeView(discord.ui.View):
    def __init__(self, subid):
        super().__init__(timeout=600)
        self.add_item(DateRangeSelect(subid))


# ─── /presscott ────────────────────────────────────────────
@tree.command(name="presscott", description="Query revenue for a sub-ID")
@app_commands.describe(subid="The campid to look up e.g. RLGRAVY2")
async def presscott(interaction: discord.Interaction, subid: str):
    await interaction.response.defer(thinking=True)
    try:
        f, t  = get_date_range("7days")
        data  = await fetch_eflow(f, t, subid.strip())
        await interaction.followup.send(
            embed=build_embed(data, subid.strip(), f, t),
            view=DateRangeView(subid.strip())
        )
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(f"❌ eFlow API error `{e.status}`: {e.message}")
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected error: `{type(e).__name__}: {e}`")


# ─── /camps ────────────────────────────────────────────────
@tree.command(name="camps", description="List all campids with clicks and revenue")
@app_commands.choices(range=[
    app_commands.Choice(name="Today",        value="today"),
    app_commands.Choice(name="Yesterday",    value="yesterday"),
    app_commands.Choice(name="Last 7 Days",  value="7days"),
    app_commands.Choice(name="Last 30 Days", value="30days"),
])
async def camps(interaction: discord.Interaction, range: str = "7days"):
    await interaction.response.defer(thinking=True)
    try:
        f, t = get_date_range(range)
        data = await fetch_eflow(f, t)
        rows = extract_rows(data)

        camps_data = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            rep     = safe_get(row, "reporting", {}) or {}
            name    = row_label(row)
            revenue = float(rep.get("revenue", 0) or 0)
            clicks  = int(rep.get("total_click", 0) or 0)
            camps_data.append((revenue, clicks, name))

        # Highest revenue first; ties broken by most clicks
        camps_data.sort(key=lambda c: (c[0], c[1]), reverse=True)

        lines = []
        for revenue, clicks, name in camps_data:
            if revenue > 0:
                lines.append(f"✅ `{name}` — ${revenue:,.2f} | {clicks} clicks")
            else:
                lines.append(f"⬜ `{name}` — No Revenue | {clicks} clicks")

        if lines:
            # Discord embed descriptions cap at 4096 chars
            desc = "\n".join(lines)
            if len(desc) > 3900:
                desc = desc[:3900] + "\n… (truncated)"
            embed = discord.Embed(
                title       = "📋 All Camps",
                description = desc,
                color       = discord.Color.blurple(),
                timestamp   = datetime.now(timezone.utc)
            )
        else:
            s       = extract_summary(data)
            revenue = float(s.get("revenue", 0) or 0)
            clicks  = int(s.get("total_click", 0) or 0)
            events  = int(s.get("event", 0) or 0)

            embed = discord.Embed(
                title       = "📋 All Camps Overview",
                description = "No per-camp breakdown returned — showing totals." if revenue or clicks or events else "No Revenue",
                color       = discord.Color.green() if revenue > 0 else discord.Color.orange(),
                timestamp   = datetime.now(timezone.utc)
            )
            embed.add_field(name="💰 Total Revenue", value=f"${revenue:,.2f}", inline=True)
            embed.add_field(name="👆 Total Clicks",  value=str(clicks),        inline=True)
            embed.add_field(name="⚡ Total Events",  value=str(events),        inline=True)

        embed.add_field(name="📅 Date Range", value=f"{f} → {t}", inline=False)
        embed.set_footer(text="Presscott · eFlow Data")
        await interaction.followup.send(embed=embed)

    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(f"❌ eFlow API error `{e.status}`: {e.message}")
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected error: `{type(e).__name__}: {e}`")


# ─── /rawcamps (debug) ─────────────────────────────────────
@tree.command(name="rawcamps", description="Show the raw API response for debugging")
async def rawcamps(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    try:
        f, t = get_date_range("7days")
        data = await fetch_eflow(f, t)
        keys = list(data.keys()) if isinstance(data, dict) else f"list of {len(data)}"
        raw  = str(data)[:1500]
        await interaction.followup.send(f"**Top-level:** `{keys}`\n```\n{raw}\n```")
    except Exception as e:
        await interaction.followup.send(f"❌ `{type(e).__name__}: {e}`")


@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user} — slash commands synced.")


client.run(DISCORD_TOKEN)
