import os
import io
import math
import asyncio
import aiohttp
import discord
import datetime
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

# ====== CONFIG ======
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
API_KEY = os.getenv("FREEFIRE_COMMUNITY_API_KEY")
INFO_URL = "https://developers.freefirecommunity.com/api/v1/info"
IMAGE_URL = "https://developers.freefirecommunity.com/api/v1/image"

if not DISCORD_TOKEN:
    raise ValueError("❌ Discord bot token missing. Set DISCORD_BOT_TOKEN before running.")
if not API_KEY:
    raise ValueError("❌ Free Fire API key missing. Set FREEFIRE_COMMUNITY_API_KEY before running.")

# ====== BOT SETUP ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

def img_url(item_id):
    if not item_id:
        return None
    return f"{IMAGE_URL}?itemID={item_id}&key={API_KEY}"

async def fetch_image(session, item_id):
    url = img_url(item_id)
    if not url:
        return None
    async with session.get(url) as resp:
        if resp.status == 200:
            data = await resp.read()
            try:
                return Image.open(io.BytesIO(data)).convert("RGBA")
            except Exception:
                return None
    return None

def draw_glow_ring(canvas, center, outer_radius, inner_radius, color=(139, 0, 0), steps=30):
    # Soft glow ring using layered circles
    cx, cy = center
    draw = ImageDraw.Draw(canvas)
    for i in range(steps):
        t = i / steps
        radius = inner_radius + (outer_radius - inner_radius) * t
        alpha = int(180 * (1 - t))
        fill = (color[0], color[1], color[2], alpha)
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        draw.ellipse(bbox, outline=fill, width=6)

def hex_points(center, size):
    cx, cy = center
    pts = []
    for k in range(6):
        ang = math.radians(60 * k - 30)  # flat-top hex
        x = cx + size * math.cos(ang)
        y = cy + size * math.sin(ang)
        pts.append((x, y))
    return pts

def draw_hex_frame(canvas, center, size, border=(139, 0, 0), fill=(30, 30, 30), shadow=True):
    draw = ImageDraw.Draw(canvas)
    pts = hex_points(center, size)
    if shadow:
        # subtle shadow
        shadow_pts = [(x + 4, y + 4) for (x, y) in pts]
        draw.polygon(shadow_pts, fill=(0, 0, 0, 120))
    draw.polygon(pts, fill=fill)
    draw.line(pts + [pts[0]], fill=border, width=4)

def paste_center(canvas, img, center, max_size):
    # Resize preserving aspect, paste centered
    w, h = img.size
    scale = min(max_size / w, max_size / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    x = int(center[0] - nw / 2)
    y = int(center[1] - nh / 2)
    canvas.paste(img, (x, y), img)
    return img

# Updated text size calculation to use textbbox()
def calculate_text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

# Updated the background to white with glowing effect and removed text elements
async def build_outfit_panel(data):
    # Canvas and styling
    W, H = 1400, 1000
    canvas = Image.new("RGBA", (W, H), (30, 30, 30, 255))  # Dark background
    draw = ImageDraw.Draw(canvas)

    # Add gradient background
    for y in range(H):
        alpha = int(255 * (1 - y / H))
        draw.line([(0, y), (W, y)], fill=(20, 20, 40, alpha))

    try:
        font_small = ImageFont.truetype("arial.ttf", 24)
    except Exception:
        font_small = ImageFont.load_default()

    center = (W // 2, H // 2)

    async with aiohttp.ClientSession() as session:
        # Collect items
        clothes = data.get("profileInfo", {}).get("clothes", []) or []
        weapons = data.get("basicInfo", {}).get("weaponSkinShows", []) or []
        pet_id = (data.get("petInfo", {}) or {}).get("id")
        items = []
        items.extend(clothes)
        items.extend(weapons)
        if pet_id:
            items.append(pet_id)

        # Include all images fetched from the API
        max_items = len(items)
        items = items[:max_items]

        # Central character (prefer avatarId, fall back to headPic)
        avatar = await fetch_image(session, (data.get("profileInfo", {}) or {}).get("avatarId"))
        if avatar is None:
            avatar = await fetch_image(session, (data.get("basicInfo", {}) or {}).get("headPic"))

        # Character backdrop plate
        if avatar:
            paste_center(canvas, avatar, center, max_size=300)  # Keep the central character smaller
        else:
            silhouette = Image.new("RGBA", (300, 300), (200, 200, 200, 120))
            paste_center(canvas, silhouette, center, max_size=300)

        # Arrange hex frames around circle
        ring_radius = 420
        n = len(items)
        if n > 0:
            for i, item_id in enumerate(items):
                angle_deg = -90 + (360 / n) * i
                ang = math.radians(angle_deg)
                ix = int(center[0] + ring_radius * math.cos(ang))
                iy = int(center[1] + ring_radius * math.sin(ang))
                item_center = (ix, iy)

                # Draw hex frame with glowing border and enhanced shadow
                draw_hex_frame(canvas, item_center, size=110, border=(255, 223, 0), fill=(255, 255, 255), shadow=True)

                # Paste item with transparent background
                img = await fetch_image(session, item_id)
                if img:
                    img = img.convert("RGBA")
                    transparent_bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    transparent_bg.paste(img, (0, 0), img)
                    paste_center(canvas, transparent_bg, item_center, max_size=120)  # Make items larger

    # Output
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    output.seek(0)
    return output

# Update embed message to show avatar ID instead of character pic
@bot.command(name="info", help="Get Free Fire player info. Usage: !info <uid> [region]")
async def info_cmd(ctx: commands.Context, uid: str, region: str = "ind"):
    await ctx.send(f"🔍 Fetching UID **{uid}**... Please wait ⏳")

    headers = {"x-api-key": API_KEY}
    params = {"uid": uid, "region": region.lower()}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(INFO_URL, headers=headers, params=params, timeout=30) as resp:
                if resp.status != 200:
                    return await ctx.send(f"❌ Wrong UID or Server ! Please Check Again({resp.status})")
                data = await resp.json()

        # ===== FIRST MESSAGE: Composite Panel =====
        panel_img = await build_outfit_panel(data)
        await ctx.send(file=discord.File(panel_img, filename="outfit_panel.png"))

        # ===== SECOND MESSAGE: Enhanced Embed =====
        basic = data.get("basicInfo", {}) or {}
        captain = data.get("captainBasicInfo", {}) or {}
        clan = data.get("clanBasicInfo", {}) or {}
        credit = data.get("creditScoreInfo", {}) or {}
        diamond = data.get("diamondCostRes", {}) or {}
        pet = data.get("petInfo", {}) or {}
        profile = data.get("profileInfo", {}) or {}
        social = data.get("socialInfo", {}) or {}

        equipped_skills = ", ".join(str(s.get("skillId")) for s in profile.get("equipedSkills", []))
        clothes_list = ", ".join(profile.get("clothes", []))

        player_name = basic.get("nickname", "Unknown")

        # Replaced all emojis with <a:610964frosty23Copy:1455989311643062515> throughout the embed message
        info_text = f"""
<a:767230peachdance:1455988990250586295>       𝐒𝐜𝐫𝐢𝐩𝐭 𝐊𝐢𝐭𝐭𝐞𝐧'𝐬 𝐈𝐧𝐟𝐨 𝐒𝐲𝐬𝐭𝐞𝐦

<a:994576pumpingpinkheart:1455989091173798121>  𝐁𝐚𝐬𝐢𝐜 𝐈𝐧𝐟𝐨

<a:610964frosty23Copy:1455989311643062515> UID: {basic.get('accountId', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Level: {basic.get('level', 'N/A')} (Exp: {basic.get('exp', 'N/A')})
<a:610964frosty23Copy:1455989311643062515> Region: {basic.get('region', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Honor Score: {credit.get('creditScore', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Likes: {basic.get('liked', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Prime Level: {basic.get('primePrivilegeDetail', {}).get('primeLevel', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Weapon Skins: {', '.join(basic.get('weaponSkinShows', []))}
<a:610964frosty23Copy:1455989311643062515> Select Occupations: {', '.join(str(occ.get('modeId')) for occ in basic.get('selectOccupations', []) if occ)}
            
<a:633186palepinkribbonsoftCopyCopy:1455989271381938300>    𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐀𝐜𝐭𝐢𝐯𝐢𝐭𝐲 

<a:610964frosty23Copy:1455989311643062515> Most Recent OB: {basic.get('releaseVersion', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> BP Badges: {captain.get('badgeCnt', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> BR Rank (points): {basic.get('rankingPoints', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> CS Rank: {basic.get('csRank', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Created At: {basic.get('createAt', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Last Login: {basic.get('lastLoginAt', 'N/A')}

<a:64382pinksparkles:1455988877058768896>     𝐀𝐜𝐜𝐨𝐮𝐧𝐭 𝐎𝐯𝐞𝐫𝐯𝐢𝐞𝐰

<a:610964frosty23Copy:1455989311643062515> Avatar ID: {profile.get('avatarId', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Banner ID: {basic.get('bannerId', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Pin ID: {basic.get('pinId', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Equipped Skills: {equipped_skills or 'N/A'}
<a:610964frosty23Copy:1455989311643062515> Clothes: {clothes_list or 'N/A'}
<a:610964frosty23Copy:1455989311643062515> Diamond Cost: {diamond.get('diamondCost', 'N/A')}

<a:994576pumpingpinkheart:1455989091173798121> 𝐏𝐞𝐭 𝐃𝐞𝐭𝐚𝐢𝐥𝐬 {'Yes' if pet.get('isSelected') else 'No'}

<a:610964frosty23Copy:1455989311643062515> Pet ID: {pet.get('id', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Pet Exp: {pet.get('exp', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Pet Level: {pet.get('level', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Pet Skin: {pet.get('skinId', 'N/A')}

<a:553988vk:1455988938086023308> 𝐆𝐮𝐢𝐥𝐝 𝐈𝐧𝐟𝐨

<a:610964frosty23Copy:1455989311643062515> Guild Name: {clan.get('clanName', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Guild ID: {clan.get('clanId', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Guild Level: {clan.get('clanLevel', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Live Members: {clan.get('memberNum', 'N/A')}/{clan.get('capacity', 'N/A')}

<a:610964frosty23Copy:1455989311643062515> Leader Name: {captain.get('nickname', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Leader UID: {captain.get('accountId', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Leader Level: {captain.get('level', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Last Login: {captain.get('lastLoginAt', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> Title: {captain.get('title', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> BR Rank (points): {captain.get('rankingPoints', 'N/A')}
<a:610964frosty23Copy:1455989311643062515> CS Rank: {captain.get('csRank', 'N/A')}

<a:610964frosty23Copy:1455989311643062515> 𝐒𝐢𝐠𝐧𝐚𝐭𝐮𝐫𝐞
{social.get('signature', 'N/A')}
""".strip()

        # Ensure all fields from the API are included in the embed
        additional_fields = {
            
        }

        for field_name, field_value in additional_fields.items():
            info_text += f"\n<a:610964frosty23Copy:1455989311643062515> {field_name}: {field_value}"

        embed = discord.Embed(
            title="Script Kittens",  # Updated title
            description=info_text,
            color=0x8B0000  # Dark red color
        )

        if basic.get("headPic"):
            embed.set_thumbnail(url=img_url(basic.get("headPic")))
        if basic.get("bannerId"):
            embed.set_image(url=img_url(basic.get("bannerId")))
        if clan.get("clanId"):
            embed.set_author(name=" Script Kittens", icon_url=img_url(clan.get("clanId")))  # Updated author field to Script Kittens

        # Ensure UID avatar is displayed in the embed message without changing text
        if basic.get("headPic"):
            embed.set_thumbnail(url=img_url(basic.get("headPic")))

        embed.set_footer(
            text=f"Requested by {ctx.author.display_name} • Made By 1shot",
            icon_url=ctx.author.display_avatar.url
        )
        embed.timestamp = datetime.datetime.now(datetime.UTC)

        await ctx.send(embed=embed)

        # ===== THIRD MESSAGE: Green Embed with Bot Commands =====
        commands_text = """
        **Available Commands**
        `!info <uid> [region]` - Get Free Fire player info.
        `!ban <uid>` - Check If Player is Banned .
        `!search <query>` - Search for a player.
        """.strip()

        commands_embed = discord.Embed(
            title="Bot Commands",
            description=commands_text,
            color=0x00FF00  # Green color
        )

        commands_embed.set_footer(
            text=f"Requested by {ctx.author.display_name} • Made By 1shot",
            icon_url=ctx.author.display_avatar.url
        )
        commands_embed.timestamp = datetime.datetime.now(datetime.UTC)

        await ctx.send(embed=commands_embed)

        # ===== REGION CODES INFORMATION =====
        region_info = """
        **Region Codes for Player's Account:**
        - `sg`: Singapore region (covers SG, ID, ME, VN, TH, CIS, EU, TW, MY, PK, BD)
        - `ind`: India region (covers IND only)
        - `br`: Brazil region (covers BR, US, NA, LATAM)

        Values are `sg`, `ind`, or `br`.
        """.strip()

        region_embed = discord.Embed(
            title="Region Codes Information",
            description=region_info,
            color=0x00FF00  # Green color
        )

        region_embed.set_footer(
            text=f"Requested by {ctx.author.display_name} • Made By 1shot",
            icon_url=ctx.author.display_avatar.url
        )
        region_embed.timestamp = datetime.datetime.now(datetime.UTC)

        await ctx.send(embed=region_embed)

    except asyncio.TimeoutError:
        await ctx.send("❌ API timeout. Try another region or try again.")
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name="channel", help="Set the channel for API commands. Usage: !channel set <channel_id>")
async def channel_set(ctx: commands.Context, action: str, channel_id: str = None):
    # Restrict command usage to a specific user ID
    if ctx.author.id != 1356335428541743104:
        return await ctx.send("❌ You do not have permission to use this command.")

    if action.lower() == "set":
        if not channel_id or not channel_id.isdigit():
            return await ctx.send("❌ Invalid channel ID. Please provide a valid numeric channel ID.")

        # Save the channel ID to a file or database (for simplicity, using a file here)
        try:
            with open("channel_config.txt", "w") as f:
                f.write(channel_id)
            await ctx.send(f"✅ Channel successfully set to <#{channel_id}>.")
        except Exception as e:
            await ctx.send(f"❌ Failed to save channel configuration: {e}")
    else:
        await ctx.send("❌ Invalid action. Use `set` to configure the channel.")

@bot.command(name="search", help="Search for a Free Fire player across all regions. Usage: !search <uid>")
async def search_cmd(ctx: commands.Context, uid: str):
    await ctx.send(f"🔍 Searching for UID **{uid}** across all regions... Please wait ⏳")

    headers = {"x-api-key": API_KEY}
    regions = ["sg", "ind", "br"]  # Supported regions

    for region in regions:
        params = {"uid": uid, "region": region}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(INFO_URL, headers=headers, params=params, timeout=30) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        # Build and send the outfit panel image
                        panel_img = await build_outfit_panel(data)
                        await ctx.send(file=discord.File(panel_img, filename="outfit_panel.png"))

                        # Build and send the embed message
                        basic = data.get("basicInfo", {}) or {}
                        embed = discord.Embed(
                            title=f"Player Info - {basic.get('nickname', 'Unknown')} ({region.upper()})",
                            description=f"UID: {uid}\nRegion: {region.upper()}\nLevel: {basic.get('level', 'N/A')}\nRank: {basic.get('rank', 'N/A')}\nLikes: {basic.get('liked', 'N/A')}",
                            color=0x00FF00
                        )
                        if basic.get("headPic"):
                            embed.set_thumbnail(url=img_url(basic.get("headPic")))
                        embed.set_footer(
                            text=f"Requested by {ctx.author.display_name}",
                            icon_url=ctx.author.display_avatar.url
                        )
                        await ctx.send(embed=embed)
                        return  # Stop searching after a successful match

                    elif resp.status == 404:
                        continue  # Try the next region if not found

        except asyncio.TimeoutError:
            await ctx.send(f"❌ Timeout while searching in region {region.upper()}. Trying the next region...")
        except Exception as e:
            await ctx.send(f"❌ Error while searching in region {region.upper()}: {e}")

    # If no match is found in any region
    await ctx.send(f"❌ UID **{uid}** not found in any region.")

@bot.command(name="ban", help="Check if a Free Fire player is banned. Usage: !ban <uid>")
async def ban_cmd(ctx: commands.Context, uid: str):
    embed = discord.Embed(
        title="Checking Ban Status",
        description=f"🔍 Checking ban status for UID **{uid}**... Please wait ⏳",
        color=0xFF0000  # Red color for emphasis
    )
    await ctx.send(embed=embed)

    headers = {"x-api-key": API_KEY}
    params = {"uid": uid}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://developers.freefirecommunity.com/api/v1/bancheck", headers=headers, params=params, timeout=30) as resp:
                if resp.status != 200:
                    error_embed = discord.Embed(
                        title="API Error",
                        description=f"❌ Unable to check ban status. Error code: {resp.status}",
                        color=0xFF0000
                    )
                    return await ctx.send(embed=error_embed)
                data = await resp.json()

        # Extract ban status
        is_banned = data.get("data", {}).get("is_banned", 0)
        ban_period = data.get("data", {}).get("period", "N/A")

        if is_banned:
            result_embed = discord.Embed(
                title="Ban Status",
                description=f"🚫 UID **{uid}** is banned. Ban period: {ban_period} days.",
                color=0xFF0000
            )
        else:
            result_embed = discord.Embed(
                title="Ban Status",
                description=f"✅ UID **{uid}** is not banned.",
                color=0x00FF00  # Green color for success
            )

        await ctx.send(embed=result_embed)

    except asyncio.TimeoutError:
        timeout_embed = discord.Embed(
            title="Timeout",
            description="❌ API timeout. Please try again later.",
            color=0xFF0000
        )
        await ctx.send(embed=timeout_embed)
    except Exception as e:
        error_embed = discord.Embed(
            title="Error",
            description=f"❌ An error occurred: {e}",
            color=0xFF0000
        )
        await ctx.send(embed=error_embed)

# ====== ENTRY POINT ======
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)