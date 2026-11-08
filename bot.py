import os
import discord
from discord import app_commands
from discord.ext import commands

# 1. Configuration des Intents (Nécessaire pour lire les membres, messages et audits)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.moderation = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ID DE VOTRE SERVEUR CENTRAL
CENTRAL_GUILD_ID = 1568910819008323594

@bot.event
async def on_ready():
    print(f"✅ Bot connecté en tant que {bot.user.name} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"🔗 {len(synced)} commande(s) slash synchronisée(s).")
    except Exception as e:
        print(f"❌ Erreur de synchronisation : {e}")

# =========================================================================
# 🏗️ CRÉATION AUTOMATIQUE DES SALONS SUR LE SERVEUR CENTRAL
# =========================================================================

@bot.event
async def on_guild_join(guild):
    """Déclenché dès que le bot est invité sur un nouveau serveur."""
    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if not central_guild:
        print(f"❌ Impossible de trouver le serveur central (ID: {CENTRAL_GUILD_ID})")
        return

    # Permissions : Seul le bot et les administrateurs du serveur central peuvent voir ces salons
    overwrites = {
        central_guild.default_role: discord.PermissionOverwrite(read_messages=False),
        central_guild.me: discord.PermissionOverwrite(read_messages=True)
    }
    
    try:
        # Création de la catégorie dédiée au serveur client
        category = await central_guild.create_category(
            name=f"📁 ── [ {guild.name[:20]} ] ──", 
            overwrites=overwrites
        )

        # Création des sous-salons de logs spécifiques
        await central_guild.create_text_channel(name=f"📋-administratif-{guild.id}", category=category)
        await central_guild.create_text_channel(name=f"⚙️-salons-{guild.id}", category=category)
        await central_guild.create_text_channel(name=f"🔨-sanctions-{guild.id}", category=category)
        await central_guild.create_text_channel(name=f"💬-messages-{guild.id}", category=category)

        print(f"✅ Catégorie et salons créés avec succès pour le serveur : {guild.name}")
    except Exception as e:
        print(f"❌ Erreur lors de la création des salons pour {guild.name} : {e}")

# =========================================================================
# 🔍 FONCTION DE ROUTAGE DES LOGS
# =========================================

async def send_central_log(guild_id: int, log_type: str, embed: discord.Embed):
    """Envoie l'embed de log dans le bon salon du serveur central."""
    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if not central_guild:
        return

    for channel in central_guild.text_channels:
        if str(guild_id) in channel.name and log_type in channel.name:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"Erreur d'envoi de log centralisé : {e}")
            break

# =========================================================================
# 📊 ÉVÉNEMENTS DE LOGS AUTOMATIQUES
# =========================================

# 1. ADMINISTRATIF (Arrivées / Départs)
@bot.event
async def on_member_join(member):
    embed = discord.Embed(
        title="📥 Nouveau Membre",
        description=f"**{member}** (`{member.id}`) a rejoint le serveur.",
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Serveur : {member.guild.name}")
    await send_central_log(member.guild.id, "administratif", embed)

@bot.event
async def on_member_remove(member):
    embed = discord.Embed(
        title="📤 Départ / Expulsion",
        description=f"**{member}** (`{member.id}`) a quitté le serveur.",
        color=discord.Color.orange()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Serveur : {member.guild.name}")
    await send_central_log(member.guild.id, "administratif", embed)

# 2. GESTION SALONS & RÔLES
@bot.event
async def on_guild_channel_create(channel):
    embed = discord.Embed(
        title="📂 Salon Créé",
        description=f"Le salon **#{channel.name}** a été créé.",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Serveur : {channel.guild.name}")
    await send_central_log(channel.guild.id, "salons", embed)

@bot.event
async def on_guild_channel_delete(channel):
    embed = discord.Embed(
        title="🗑️ Salon Supprimé",
        description=f"Le salon **#{channel.name}** a été supprimé.",
        color=discord.Color.red()
    )
    embed.set_footer(text=f"Serveur : {channel.guild.name}")
    await send_central_log(channel.guild.id, "salons", embed)

@bot.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        added_roles = [r.name for r in after.roles if r not in before.roles]
        removed_roles = [r.name for r in before.roles if r not in after.roles]
        
        embed = discord.Embed(
            title="🎭 Modification de Rôles",
            description=f"Mise à jour des rôles pour **{after.mention}**",
            color=discord.Color.gold()
        )
        if added_roles:
            embed.add_field(name="➕ Rôles ajoutés", value=", ".join(added_roles), inline=False)
        if removed_roles:
            embed.add_field(name="➖ Rôles retirés", value=", ".join(removed_roles), inline=False)
            
        embed.set_footer(text=f"Serveur : {after.guild.name}")
        await send_central_log(after.guild.id, "salons", embed)

# 3. SANCTIONS (Bans)
@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(
        title="🔨 Membre Banni",
        description=f"L'utilisateur **{user}** (`{user.id}`) a été banni.",
        color=discord.Color.dark_red()
    )
    embed.set_footer(text=f"Serveur : {guild.name}")
    await send_central_log(guild.id, "sanctions", embed)

# 4. MESSAGES SUPPRIMÉS
@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
        
    embed = discord.Embed(
        title="🗑️ Message Supprimé",
        description=f"Message de **{message.author.mention}** supprimé dans {message.channel.mention}.",
        color=discord.Color.red()
    )
    embed.add_field(name="Contenu", value=message.content[:1024] if message.content else "*[Média ou Embed]*", inline=False)
    embed.set_footer(text=f"Serveur : {message.guild.name}")
    await send_central_log(message.guild.id, "messages", embed)

# =========================================================================
# 🚀 LANCEMENT DU BOT (Via variable d'environnement ou directement)
# =========================================================================
TOKEN = os.getenv("DISCORD_TOKEN", "METTEZ_VOTRE_NOUVEAU_TOKEN_ICI")
bot.run(TOKEN)
