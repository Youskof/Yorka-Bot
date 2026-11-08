import os
import asyncio
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.moderation = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

CENTRAL_GUILD_ID = 1568910819008323594

# Structures de suivi en mémoire
raid_tracker = {}     # {guild_id: [timestamps]}
channel_tracker = {}  # {guild_id: [timestamps]}
paused_tickets = set()
blocked_users = set()
locked_down_servers = set()

@bot.event
async def on_ready():
    print(f"✅ Bot connecté en tant que {bot.user.name} (ID: {bot.user.id})")
    
    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if central_guild:
        cat_gestion = discord.utils.get(central_guild.categories, name="⚙️ ── [ GESTION DU BOT ] ──")
        if not cat_gestion:
            overwrites = {
                central_guild.default_role: discord.PermissionOverwrite(read_messages=False),
                central_guild.me: discord.PermissionOverwrite(read_messages=True)
            }
            cat_gestion = await central_guild.create_category(name="⚙️ ── [ GESTION DU BOT ] ──", overwrites=overwrites)
            await central_guild.create_text_channel(name="🤖-statut-global", category=cat_gestion)
            await central_guild.create_text_channel(name="🚨-erreurs-globales", category=cat_gestion)

        cat_ticket = discord.utils.get(central_guild.categories, name="📩 ── [ TICKETS MP ] ──")
        if not cat_ticket:
            overwrites = {
                central_guild.default_role: discord.PermissionOverwrite(read_messages=False),
                central_guild.me: discord.PermissionOverwrite(read_messages=True)
            }
            await central_guild.create_category(name="📩 ── [ TICKETS MP ] ──", overwrites=overwrites)

    try:
        synced = await bot.tree.sync()
        print(f"🔗 {len(synced)} commande(s) synchronisée(s).")
    except Exception as e:
        print(f"❌ Erreur de synchronisation : {e}")

# =========================================================================
# 🚨 BOUTON INTERACTIF DE CONFINEMENT D'URGENCE (Sur les alertes globales)
# =========================================================================

class LockdownView(discord.ui.View):
    def __init__(self, target_guild_id: int):
        super().__init__(timeout=None)
        self.target_guild_id = target_guild_id

    @discord.ui.button(label="🚨 Activer le Confinement d'Urgence", style=discord.ButtonStyle.danger, custom_id="lockdown_btn")
    async def lockdown_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        target_guild = bot.get_guild(self.target_guild_id)
        if not target_guild:
            await interaction.response.send_message("❌ Serveur introuvable.", ephemeral=True)
            return

        if self.target_guild_id in locked_down_servers:
            await interaction.response.send_message("⚠️ Ce serveur est déjà en confinement !", ephemeral=True)
            return

        locked_down_servers.add(self.target_guild_id)
        button.disabled = True
        button.label = "🔒 Serveur Confiné"
        await interaction.message.edit(view=self)

        for channel in target_guild.text_channels:
            try:
                await channel.set_permissions(target_guild.default_role, send_messages=False)
            except Exception:
                pass

        target_channel = target_guild.system_channel
        if not target_channel:
            for ch in target_guild.text_channels:
                if "annonce" in ch.name or "general" in ch.name or "général" in ch.name:
                    target_channel = ch
                    break
            if not target_channel and target_guild.text_channels:
                target_channel = target_guild.text_channels[0]

        if target_channel:
            try:
                msg = (
                    f"@everyone 🚨 **ALERTE : MISE EN CONFINEMENT D'URGENCE DU SERVEUR !** 🚨\n\n"
                    f"Une activité suspecte ou un raid a été détecté. La sécurité a immédiatement verrouillé les accès.\n\n"
                    f"<u>Les membres du staff (administrateurs/fondateurs) sont invités à MP le bot pour lever la mise en confinement.</u>"
                )
                await target_channel.send(msg)
            except Exception:
                pass

        await interaction.response.send_message(f"🔒 **Confinement activé avec succès** sur le serveur **{target_guild.name}**.", ephemeral=True)

# =========================================================================
# 📩 VUE INTERACTIVE DES BOUTONS DE TICKETS (Intégrée au salon ticket)
# =========================================================================

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Pause / Reprendre", style=discord.ButtonStyle.secondary, emoji="⏸️", custom_id="ticket_pause_btn")
    async def pause_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_id = interaction.channel.id
        if channel_id in paused_tickets:
            paused_tickets.remove(channel_id)
            button.label = "Pause / Reprendre"
            button.style = discord.ButtonStyle.secondary
            await interaction.response.edit_message(view=self)
            await interaction.channel.send("▶️ **Le ticket a été réactivé.**")
            
            if interaction.channel.topic and "ID_USER:" in interaction.channel.topic:
                user_id = int(interaction.channel.topic.split("ID_USER:")[1].strip())
                user = bot.get_user(user_id)
                if user:
                    try: await user.send("▶️ Votre ticket a été réactivé par l'administration.")
                    except Exception: pass
        else:
            paused_tickets.add(channel_id)
            button.label = "Reprendre"
            button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
            await interaction.channel.send("⏸️ **Le ticket a été mis en pause.**")
            
            if interaction.channel.topic and "ID_USER:" in interaction.channel.topic:
                user_id = int(interaction.channel.topic.split("ID_USER:")[1].strip())
                user = bot.get_user(user_id)
                if user:
                    try: await user.send("⏸️ Votre ticket a été mis en attente par l'administration.")
                    except Exception: pass

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.channel.topic and "ID_USER:" in interaction.channel.topic:
            user_id = int(interaction.channel.topic.split("ID_USER:")[1].strip())
            user = bot.get_user(user_id)
            if user:
                try: await user.send("🔒 Votre ticket avec l'administration a été fermé.")
                except Exception: pass

        if interaction.channel.id in paused_tickets:
            paused_tickets.remove(interaction.channel.id)

        await interaction.response.send_message("🔒 Fermeture du ticket dans 5 secondes...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

    @discord.ui.button(label="Bloquer", style=discord.ButtonStyle.danger, emoji="🚫", custom_id="ticket_block_btn")
    async def block_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.channel.topic and "ID_USER:" in interaction.channel.topic:
            user_id = int(interaction.channel.topic.split("ID_USER:")[1].strip())
            blocked_users.add(user_id)
            user = bot.get_user(user_id)
            if user:
                try: await user.send("🚫 Vous avez été bloqué du système de support.")
                except Exception: pass

        await interaction.response.send_message("🚫 Utilisateur bloqué. Fermeture du salon dans 5 secondes...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

# =========================================================================
# 📩 GESTION DES MP (TICKETS & DÉCONFINEMENT STAFF)
# =========================================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 1. Réception d'un MP
    if isinstance(message.channel, discord.DMChannel):
        
        # Commande staff pour lever le confinement via MP : "unlock ID"
        content_lower = message.content.strip().lower()
        if "unlock" in content_lower or "lever" in content_lower:
            import re
            numbers = re.findall(r'\d{17,20}', message.content)
            if numbers:
                guild_id_to_unlock = int(numbers[0])
                target_guild = bot.get_guild(guild_id_to_unlock)
                if target_guild:
                    member_in_guild = target_guild.get_member(message.author.id)
                    if member_in_guild and member_in_guild.guild_permissions.administrator:
                        if guild_id_to_unlock in locked_down_servers:
                            locked_down_servers.remove(guild_id_to_unlock)
                            for channel in target_guild.text_channels:
                                try:
                                    await channel.set_permissions(target_guild.default_role, send_messages=None)
                                except Exception: pass
                            if target_guild.system_channel:
                                await target_guild.system_channel.send("✅ **Le confinement d'urgence a été levé par un administrateur.**")
                            await message.channel.send(f"✅ Confinement levé avec succès sur **{target_guild.name}**.")
                            return
                        else:
                            await message.channel.send("⚠️ Ce serveur n'est pas en confinement.")
                            return
                    else:
                        await message.channel.send("❌ Vous n'êtes pas administrateur sur ce serveur.")
                        return

        if message.author.id in blocked_users:
            await message.channel.send("❌ Vous avez été bloqué du système de support/tickets.")
            return

        central_guild = bot.get_guild(CENTRAL_GUILD_ID)
        if not central_guild: return

        cat_ticket = discord.utils.get(central_guild.categories, name="📩 ── [ TICKETS MP ] ──")
        if not cat_ticket: return

        clean_name = "".join(c for c in message.author.name.lower() if c.isalnum() or c in "-_")
        channel_name = f"ticket-{clean_name}"
        ticket_channel = discord.utils.get(cat_ticket.text_channels, name=channel_name)

        # Création automatique du salon de ticket avec les boutons interactifs intégrés
        if not ticket_channel:
            ticket_channel = await central_guild.create_text_channel(
                name=channel_name,
                category=cat_ticket,
                topic=f"ID_USER:{message.author.id}"
            )
            
            embed_welcome = discord.Embed(
                title=f"📩 Nouveau Ticket MP ouvert — {message.author}",
                description=f"**Utilisateur :** {message.author.mention} (`{message.author.id}`)\n\n"
                            f"⚙️ **Actions rapides :** Utilisez les boutons ci-dessous pour gérer ce ticket.\n"
                            f"💡 *Pour lever un confinement par MP, envoyez : `unlock ID_DU_SERVEUR`*",
                color=discord.Color.blue()
            )
            embed_welcome.set_thumbnail(url=message.author.display_avatar.url)
            
            # Envoi de l'embed avec les boutons de contrôle interactifs
            await ticket_channel.send(embed=embed_welcome, view=TicketControlView())
            await message.channel.send("✅ Votre message a bien été transmis à l'équipe centralisée.")

        if ticket_channel.id in paused_tickets:
            await message.channel.send("⏸️ Votre ticket est actuellement en pause.")
            return

        embed_msg = discord.Embed(description=message.content, color=discord.Color.light_grey(), timestamp=datetime.now())
        embed_msg.set_author(name=f"{message.author} (MP)", icon_url=message.author.display_avatar.url)
        if message.attachments:
            embed_msg.set_image(url=message.attachments[0].url)
        await ticket_channel.send(embed=embed_msg)

    # 2. Réponse de la Centrale vers le MP de l'utilisateur
    elif message.guild and message.guild.id == CENTRAL_GUILD_ID:
        if message.channel.category and message.channel.category.name == "📩 ── [ TICKETS MP ] ──":
            if message.content.startswith("/") or message.content.startswith("!"):
                await bot.process_commands(message)
                return
            if message.channel.id in paused_tickets:
                return

            if message.channel.topic and "ID_USER:" in message.channel.topic:
                user_id = int(message.channel.topic.split("ID_USER:")[1].strip())
                user = bot.get_user(user_id)
                if user:
                    try:
                        embed_reply = discord.Embed(title="💬 Réponse du Support", description=message.content, color=discord.Color.green())
                        if message.attachments:
                            embed_reply.set_image(url=message.attachments[0].url)
                        await user.send(embed=embed_reply)
                        await message.add_reaction("✅")
                    except Exception:
                        await message.channel.send("❌ Impossible d'envoyer le MP à l'utilisateur.")

    await bot.process_commands(message)

# =========================================================================
# ⚙️ COMMANDES SLASH DE GESTION DES TICKETS (Optionnelles si boutons utilisés)
# =========================================================================

@bot.tree.command(name="ticket-pause", description="Met le ticket en pause.")
async def ticket_pause(interaction: discord.Interaction):
    if interaction.guild_id != CENTRAL_GUILD_ID or not interaction.channel.category or interaction.channel.category.name != "📩 ── [ TICKETS MP ] ──":
        await interaction.response.send_message("❌ Réservé aux salons de tickets.", ephemeral=True)
        return
    if interaction.channel.id in paused_tickets:
        paused_tickets.remove(interaction.channel.id)
        await interaction.response.send_message("▶️ Ticket réactivé.")
    else:
        paused_tickets.add(interaction.channel.id)
        await interaction.response.send_message("⏸️ Ticket mis en pause.")

@bot.tree.command(name="ticket-close", description="Ferme le ticket.")
async def ticket_close(interaction: discord.Interaction):
    if interaction.guild_id != CENTRAL_GUILD_ID or not interaction.channel.category or interaction.channel.category.name != "📩 ── [ TICKETS MP ] ──":
        await interaction.response.send_message("❌ Réservé aux salons de tickets.", ephemeral=True)
        return
    await interaction.response.send_message("🔒 Fermeture dans 5 secondes...")
    await asyncio.sleep(5)
    await interaction.channel.delete()

@bot.tree.command(name="ticket-block", description="Bloque l'utilisateur.")
async def ticket_block(interaction: discord.Interaction):
    if interaction.guild_id != CENTRAL_GUILD_ID or not interaction.channel.category or interaction.channel.category.name != "📩 ── [ TICKETS MP ] ──":
        await interaction.response.send_message("❌ Réservé aux salons de tickets.", ephemeral=True)
        return
    if interaction.channel.topic and "ID_USER:" in interaction.channel.topic:
        blocked_users.add(int(interaction.channel.topic.split("ID_USER:")[1].strip()))
    await interaction.response.send_message("🚫 Utilisateur bloqué. Fermeture...")
    await asyncio.sleep(5)
    await interaction.channel.delete()

# =========================================================================
# 🚨 DÉTECTION SÉCURITÉ (Anti-Raid, Mass Pings, Mass Suppressions)
# =========================================================================

async def trigger_security_alert(guild: discord.Guild, title: str, description: str):
    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if not central_guild: return

    for channel in central_guild.text_channels:
        if "erreurs-globales" in channel.name:
            embed = discord.Embed(title=f"🚨 {title}", description=description, color=discord.Color.red(), timestamp=datetime.now())
            view = LockdownView(guild.id)
            await channel.send(embed=embed, view=view)
            break

@bot.event
async def on_member_join(member):
    now = datetime.now()
    guild_id = member.guild.id
    if guild_id not in raid_tracker: raid_tracker[guild_id] = []

    raid_tracker[guild_id] = [t for t in raid_tracker[guild_id] if now - t < timedelta(seconds=10)]
    raid_tracker[guild_id].append(now)

    if len(raid_tracker[guild_id]) >= 5:
        await trigger_security_alert(
            member.guild,
            "ALERTE AFFLUX MASSIF (ANTI-RAID)",
            f"Vague anormale de membres détectée sur **{member.guild.name}** (`{member.guild.id}`).\n"
            f"📊 `{len(raid_tracker[guild_id])}` arrivées en moins de 10 secondes."
        )
        raid_tracker[guild_id].clear()

    embed = discord.Embed(title="📥 Nouveau Membre", description=f"**{member}** (`{member.id}`) a rejoint le serveur.", color=discord.Color.green())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Serveur : {member.guild.name}")
    await send_central_log(member.guild.id, "administratif", embed)

@bot.event
async def on_guild_channel_delete(channel):
    now = datetime.now()
    guild_id = channel.guild.id
    if guild_id not in channel_tracker: channel_tracker[guild_id] = []

    channel_tracker[guild_id] = [t for t in channel_tracker[guild_id] if now - t < timedelta(seconds=10)]
    channel_tracker[guild_id].append(now)

    if len(channel_tracker[guild_id]) >= 3:
        await trigger_security_alert(
            channel.guild,
            "🚨 ALERTE SUPPRESSION MASSIVE DE SALONS",
            f"Attention ! Suppression en masse de salons détectée sur **{channel.guild.name}**.\n"
            f"🗑️ `{len(channel_tracker[guild_id])}` salons supprimés rapidement."
        )
        channel_tracker[guild_id].clear()

    embed = discord.Embed(title="🗑️ Salon Supprimé", description=f"Le salon **#{channel.name}** a été supprimé.", color=discord.Color.red())
    embed.set_footer(text=f"Serveur : {channel.guild.name}")
    await send_central_log(channel.guild.id, "salons", embed)

# =========================================================================
# 🏗️ CRÉATION DES SALONS ET FICHE INFO LORS DE L'AJOUT
# =========================================================================

@bot.event
async def on_guild_join(guild):
    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if not central_guild: return

    overwrites = {
        central_guild.default_role: discord.PermissionOverwrite(read_messages=False),
        central_guild.me: discord.PermissionOverwrite(read_messages=True)
    }
    
    try:
        category = await central_guild.create_category(name=f"📁 ── [ {guild.name[:20]} ] ──", overwrites=overwrites)
        await central_guild.create_text_channel(name=f"📋-administratif-{guild.id}", category=category)
        await central_guild.create_text_channel(name=f"⚙️-salons-{guild.id}", category=category)
        await central_guild.create_text_channel(name=f"🔨-sanctions-{guild.id}", category=category)
        await central_guild.create_text_channel(name=f"💬-messages-{guild.id}", category=category)

        total_members = guild.member_count
        bots_count = sum(1 for m in guild.members if m.bot)
        humans_count = total_members - bots_count
        admins_count = sum(1 for m in guild.members if m.guild_permissions.administrator and not m.bot)
        
        inviter = "Inconnu"
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
                if entry.target.id == bot.user.id:
                    inviter = f"{entry.user.mention} (`{entry.user}`)"
                    break
        except Exception: pass

        embed = discord.Embed(title=f"📊 Fiche Serveur — {guild.name}", color=discord.Color.blurple())
        if guild.icon: embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="🆔 ID du Serveur", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="👑 Propriétaire", value=f"{guild.owner.mention}" if guild.owner else "Inconnu", inline=True)
        embed.add_field(name="📥 Invité par", value=inviter, inline=False)
        embed.add_field(name="👥 Membres", value=str(total_members), inline=True)
        embed.add_field(name="🛡️ Admins", value=str(admins_count), inline=True)

        for channel in central_guild.text_channels:
            if "statut-global" in channel.name:
                await channel.send(embed=embed)
                break
    except Exception as e:
        print(f"Erreur join: {e}")

# Fonctions annexes de logs
async def send_central_log(guild_id: int, log_type: str, embed: discord.Embed):
    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if not central_guild: return
    for channel in central_guild.text_channels:
        if str(guild_id) in channel.name and log_type in channel.name:
            try: await channel.send(embed=embed)
            except Exception: pass
            break

@bot.event
async def on_member_remove(member):
    embed = discord.Embed(title="📤 Départ", description=f"**{member}** a quitté le serveur.", color=discord.Color.orange())
    await send_central_log(member.guild.id, "administratif", embed)

@bot.event
async def on_guild_channel_create(channel):
    embed = discord.Embed(title="📂 Salon Créé", description=f"**#{channel.name}** créé.", color=discord.Color.blue())
    await send_central_log(channel.guild.id, "salons", embed)

@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(title="🔨 Banni", description=f"**{user}** banni.", color=discord.Color.dark_red())
    await send_central_log(guild.id, "sanctions", embed)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild: return
    embed = discord.Embed(title="🗑️ Message Supprimé", description=f"Par {message.author.mention} dans {message.channel.mention}.", color=discord.Color.red())
    await send_central_log(message.guild.id, "messages", embed)

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
