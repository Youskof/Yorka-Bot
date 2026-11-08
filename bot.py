import os
import discord
from discord import app_commands
from discord.ext import commands

# 1. Configuration des Intents
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
    
    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if central_guild:
        category_name = "⚙️ ── [ GESTION DU BOT ] ──"
        category = discord.utils.get(central_guild.categories, name=category_name)
        
        if not category:
            overwrites = {
                central_guild.default_role: discord.PermissionOverwrite(read_messages=False),
                central_guild.me: discord.PermissionOverwrite(read_messages=True)
            }
            category = await central_guild.create_category(name=category_name, overwrites=overwrites)
            
            await central_guild.create_text_channel(name="🤖-statut-global", category=category)
            await central_guild.create_text_channel(name="🚨-erreurs-globales", category=category)
            print("✅ Salons de gestion globale créés sur le serveur central.")

    try:
        synced = await bot.tree.sync()
        print(f"🔗 {len(synced)} commande(s) slash synchronisée(s).")
    except Exception as e:
        print(f"❌ Erreur de synchronisation : {e}")

# =========================================================================
# 🏗️ CRÉATION DES SALONS ET FICHE INFO LORS DE L'AJOUT SUR UN SERVEUR
# =========================================================================

@bot.event
async def on_guild_join(guild):
    """Déclenché dès que le bot rejoint un serveur : crée les logs et la fiche info."""
    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if not central_guild:
        print(f"❌ Impossible de trouver le serveur central.")
        return

    overwrites = {
        central_guild.default_role: discord.PermissionOverwrite(read_messages=False),
        central_guild.me: discord.PermissionOverwrite(read_messages=True)
    }
    
    try:
        # 1. Création de la catégorie et des salons de logs du serveur
        category = await central_guild.create_category(
            name=f"📁 ── [ {guild.name[:20]} ] ──", 
            overwrites=overwrites
        )

        await central_guild.create_text_channel(name=f"📋-administratif-{guild.id}", category=category)
        await central_guild.create_text_channel(name=f"⚙️-salons-{guild.id}", category=category)
        await central_guild.create_text_channel(name=f"🔨-sanctions-{guild.id}", category=category)
        await central_guild.create_text_channel(name=f"💬-messages-{guild.id}", category=category)

        # 2. Calcul des statistiques du serveur
        total_members = guild.member_count
        bots_count = sum(1 for m in guild.members if m.bot)
        humans_count = total_members - bots_count
        admins_count = sum(1 for m in guild.members if m.guild_permissions.administrator and not m.bot)
        
        # Récupération de l'auteur de l'invitation via l'historique d'audit (si le bot a la perperm)
        inviter = "Inconnu (Permissions insuffisantes)"
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
                if entry.target.id == bot.user.id:
                    inviter = f"{entry.user.mention} (`{entry.user}`)"
                    break
        except Exception:
            pass

        # 3. Construction de la Fiche Info Détaillée
        embed = discord.Embed(
            title=f"📊 Fiche Serveur — {guild.name}",
            description=f"Le bot vient d'être intégré sur un nouveau serveur !",
            color=discord.Color.blurple()
        )
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="🆔 ID du Serveur", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="👑 Propriétaire", value=f"{guild.owner.mention} (`{guild.owner}`)" if guild.owner else "Inconnu", inline=True)
        embed.add_field(name="📥 Invité par", value=inviter, inline=False)
        
        embed.add_field(name="👥 Membres Totaux", value=str(total_members), inline=True)
        embed.add_field(name="👤 Humains", value=str(humans_count), inline=True)
        embed.add_field(name="🤖 Bots", value=str(bots_count), inline=True)
        
        embed.add_field(name="🛡️ Administrateurs", value=str(admins_count), inline=True)
        embed.add_field(name="💬 Salons textuels", value=str(len(guild.text_channels)), inline=True)
        embed.add_field(name="🔊 Salons vocaux", value=str(len(guild.voice_channels)), inline=True)
        
        embed.set_footer(text=f"ID du Propriétaire : {guild.owner.id if guild.owner else 'N/A'}")

        # 4. Envoi de la fiche dans le salon #🤖-statut-global de la centrale
        for channel in central_guild.text_channels:
            if "statut-global" in channel.name:
                await channel.send(embed=embed)
                break

        print(f"✅ Fiche info et salons générés avec succès pour : {guild.name}")
    except Exception as e:
        print(f"❌ Erreur lors de la génération de la fiche pour {guild.name} : {e}")

# =========================================================================
# 🔍 FONCTION DE ROUTAGE DES LOGS
# =========================================================================

async def send_central_log(guild_id: int, log_type: str, embed: discord.Embed):
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

@bot.event
async def on_member_join(member):
    embed = discord.Embed(title="📥 Nouveau Membre", description=f"**{member}** (`{member.id}`) a rejoint le serveur.", color=discord.Color.green())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Serveur : {member.guild.name}")
    await send_central_log(member.guild.id, "administratif", embed)

@bot.event
async def on_member_remove(member):
    embed = discord.Embed(title="📤 Départ / Expulsion", description=f"**{member}** (`{member.id}`) a quitté le serveur.", color=discord.Color.orange())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Serveur : {member.guild.name}")
    await send_central_log(member.guild.id, "administratif", embed)

@bot.event
async def on_guild_channel_create(channel):
    embed = discord.Embed(title="📂 Salon Créé", description=f"Le salon **#{channel.name}** a été créé.", color=discord.Color.blue())
    embed.set_footer(text=f"Serveur : {channel.guild.name}")
    await send_central_log(channel.guild.id, "salons", embed)

@bot.event
async def on_guild_channel_delete(channel):
    embed = discord.Embed(title="🗑️ Salon Supprimé", description=f"Le salon **#{channel.name}** a été supprimé.", color=discord.Color.red())
    embed.set_footer(text=f"Serveur : {channel.guild.name}")
    await send_central_log(channel.guild.id, "salons", embed)

@bot.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        added_roles = [r.name for r in after.roles if r not in before.roles]
        removed_roles = [r.name for r in before.roles if r not in after.roles]
        
        embed = discord.Embed(title="🎭 Modification de Rôles", description=f"Mise à jour des rôles pour **{after.mention}**", color=discord.Color.gold())
        if added_roles: embed.add_field(name="➕ Rôles ajoutés", value=", ".join(added_roles), inline=False)
        if removed_roles: embed.add_field(name="➖ Rôles retirés", value=", ".join(removed_roles), inline=False)
        embed.set_footer(text=f"Serveur : {after.guild.name}")
        await send_central_log(after.guild.id, "salons", embed)

@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(title="🔨 Membre Banni", description=f"L'utilisateur **{user}** (`{user.id}`) a été banni.", color=discord.Color.dark_red())
    embed.set_footer(text=f"Serveur : {guild.name}")
    await send_central_log(guild.id, "sanctions", embed)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild: return
    embed = discord.Embed(title="🗑️ Message Supprimé", description=f"Message de **{message.author.mention}** supprimé dans {message.channel.mention}.", color=discord.Color.red())
    embed.add_field(name="Contenu", value=message.content[:1024] if message.content else "*[Média ou Embed]*", inline=False)
    embed.set_footer(text=f"Serveur : {message.guild.name}")
    await send_central_log(message.guild.id, "messages", embed)

# Lancement du bot
TOKEN = os.getenv("DISCORD_TOKEN", "METTEZ_VOTRE_TOKEN_ICI")
bot.run(TOKEN)
