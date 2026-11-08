import os
import asyncio
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from google import genai

# 1. Configuration des Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.moderation = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ID DU SERVEUR CENTRAL
CENTRAL_GUILD_ID = 1568910819008323594

# Initialisation du client Gemini AI
# (Récupère automatiquement la clé depuis la variable d'environnement GEMINI_API_KEY)
ai_client = genai.Client()

# Structures de suivi en mémoire
raid_tracker = {}     # {guild_id: [timestamps]}
channel_tracker = {}  # {guild_id: [timestamps]}
paused_tickets = set()
blocked_users = set()
locked_down_servers = set()
ai_handled_tickets = set() # Pour savoir si l'IA gère le ticket ou si un humain a repris

# =========================================================================
# 📜 FONCTION D'AUTO-MISE À JOUR DU SALON COMMANDES
# =========================================================================

async def update_help_channel():
    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if not central_guild:
        return

    cat_gestion = discord.utils.get(central_guild.categories, name="⚙️ ── [ GESTION DU BOT ] ──")
    if not cat_gestion:
        return

    help_channel = discord.utils.get(cat_gestion.text_channels, name="📜-commandes-bot")
    if not help_channel:
        help_channel = await central_guild.create_text_channel(name="📜-commandes-bot", category=cat_gestion)
        print("✅ Salon #📜-commandes-bot créé.")

    embed = discord.Embed(
        title="📚 DOCUMENTATION AUTOMATIQUE — COMMANDES & ACTIONS DU BOT",
        description="Ce salon est mis à jour automatiquement par le bot à chaque mise à jour ou ajout de fonctionnalités.",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )

    embed.add_field(
        name="🤖 SUPPORT INTELLIGENT (IA GEMINI)",
        value="• **Réponse Automatique par IA** : Les tickets MP reçoivent une analyse et une réponse intelligente propulsée par Gemini 24h/24, tant qu'un administrateur n'a pas pris le relais manuellement.",
        inline=False
    )

    embed.add_field(
        name="🔨 MODÉRATION GLOBALE (Slash Commands)",
        value=(
            "• `/global-ban user_id:<ID> raison:<motif>` : Bannit l'utilisateur de **tous** les serveurs du réseau d'un coup + envoie un MP à la cible et trace l'action dans `#🔨-sanctions-globales`.\n"
            "• `/global-kick user_id:<ID> raison:<motif>` : Expulse l'utilisateur de **tous** les serveurs du réseau + notification MP et log."
        ),
        inline=False
    )

    embed.add_field(
        name="📊 GESTION & INFRASTRUCTURE (Slash Commands)",
        value=(
            "• `/stats-reseau` : Affiche les statistiques en direct du réseau (nombre de serveurs, membres cumulés, salons surveillés, confinements actifs).\n"
            "• `/diffuser titre:<titre> message:<texte>` : Diffuse une annonce officielle stylisée dans le salon principal de **tous** les serveurs clients."
        ),
        inline=False
    )

    embed.add_field(
        name="📩 GESTION DES TICKETS MP (Boutons sous l'Embed)",
        value=(
            "• `⏸️ Pause / Reprendre` : Met en pause le ticket ou le réactive.\n"
            "• `🔒 Fermer` : Ferme et supprime le salon de ticket central après notification au membre.\n"
            "• `🚫 Bloquer` : Bloque l'utilisateur du système de support et détruit le salon."
        ),
        inline=False
    )

    embed.add_field(
        name="🚨 SÉCURITÉ & PROTOCOLE ANTI-RAID",
        value=(
            "• **Détection automatique** : Surveillance des pings de masse, vagues d'arrivées et suppressions de salons.\n"
            "• **Confinement d'Urgence** : Bouton rouge interactif dans `#🚨-erreurs-globales` pour verrouiller le serveur ciblé et faire une annonce `@everyone`.\n"
            "• **Levée du confinement** : Un administrateur peut lever le confinement à tout moment en envoyant en MP au bot : `unlock <ID_DU_SERVEUR>`."
        ),
        inline=False
    )

    embed.set_footer(text="Système de documentation dynamique • Propulsé par Gemini AI")

    async for message in help_channel.history(limit=10):
        if message.author == bot.user and message.embeds:
            await message.edit(embed=embed)
            print("✅ Salon #📜-commandes-bot mis à jour avec succès.")
            return

    await help_channel.send(embed=embed)
    print("✅ Documentation envoyée dans #📜-commandes-bot.")

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
            await central_guild.create_text_channel(name="🔨-sanctions-globales", category=cat_gestion)

        cat_ticket = discord.utils.get(central_guild.categories, name="📩 ── [ TICKETS MP ] ──")
        if not cat_ticket:
            overwrites = {
                central_guild.default_role: discord.PermissionOverwrite(read_messages=False),
                central_guild.me: discord.PermissionOverwrite(read_messages=True)
            }
            await central_guild.create_category(name="📩 ── [ TICKETS MP ] ──", overwrites=overwrites)

        await update_help_channel()

    try:
        synced = await bot.tree.sync()
        print(f"🔗 {len(synced)} commande(s) synchronisée(s).")
    except Exception as e:
        print(f"❌ Erreur de synchronisation : {e}")

# =========================================================================
# 🚨 BOUTON INTERACTIF DE CONFINEMENT D'URGENCE
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
# 📩 VUE INTERACTIVE DES BOUTONS DE TICKETS (Support MP)
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
        if interaction.channel.id in ai_handled_tickets:
            ai_handled_tickets.remove(interaction.channel.id)

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

        if interaction.channel.id in ai_handled_tickets:
            ai_handled_tickets.remove(interaction.channel.id)

        await interaction.response.send_message("🚫 Utilisateur bloqué. Fermeture du salon dans 5 secondes...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

# =========================================================================
# 📩 GESTION DES MP (TICKETS, SUPPORT IA & DÉCONFINEMENT STAFF)
# =========================================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 1. Réception d'un MP d'un utilisateur
    if isinstance(message.channel, discord.DMChannel):
        content_clean = message.content.strip().lower()

        # Commande staff pour lever le confinement via MP : "unlock ID"
        if "unlock" in content_clean or "lever" in content_clean:
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

        is_new_ticket = False
        if not ticket_channel:
            is_new_ticket = True
            ticket_channel = await central_guild.create_text_channel(
                name=channel_name,
                category=cat_ticket,
                topic=f"ID_USER:{message.author.id}"
            )
            ai_handled_tickets.add(ticket_channel.id) # Active l'IA par défaut sur le nouveau ticket
            
            embed_welcome = discord.Embed(
                title=f"📩 Nouveau Ticket MP ouvert — {message.author}",
                description=f"**Utilisateur :** {message.author.mention} (`{message.author.id}`)\n\n"
                            f"🤖 **Support IA Actif** (Gemini gère les réponses automatiques jusqu'à intervention d'un admin).\n"
                            f"⚙️ **Actions rapides :** Utilisez les boutons ci-dessous.",
                color=discord.Color.blue()
            )
            embed_welcome.set_thumbnail(url=message.author.display_avatar.url)
            await ticket_channel.send(embed=embed_welcome, view=TicketControlView())

        if ticket_channel.id in paused_tickets:
            await message.channel.send("⏸️ Votre ticket est actuellement en pause.")
            return

        # Transmission de la question dans le salon central
        embed_msg = discord.Embed(description=message.content, color=discord.Color.light_grey(), timestamp=datetime.now())
        embed_msg.set_author(name=f"{message.author} (MP)", icon_url=message.author.display_avatar.url)
        if message.attachments:
            embed_msg.set_image(url=message.attachments[0].url)
        await ticket_channel.send(embed=embed_msg)

        # Réponse automatique via l'IA Gemini si aucun humain n'a pris le relais
        if ticket_channel.id in ai_handled_tickets:
            try:
                # Utilisation du modèle gemini-2.5-flash (rapide et parfait pour le support)
                prompt_system = (
                    "Tu es l'assistant virtuel officiel d'une administration centralisée de serveurs Discord. "
                    "Tu réponds aux utilisateurs en MP de manière polie, claire, professionnelle et rassurante. "
                    "Précise-leur que leur message a bien été transmis aux administrateurs humains et réponds à leur question s'ils en ont une."
                )
                response = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"{prompt_system}\n\nMessage de l'utilisateur : {message.content}"
                )
                ai_reply_text = response.text

                embed_ai = discord.Embed(
                    title="🤖 Assistant Virtuel (IA)",
                    description=ai_reply_text,
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                embed_ai.set_footer(text="🤖 Réponse automatique générée par Gemini AI")
                await message.channel.send(embed=embed_ai)

                # Copie de la réponse de l'IA dans le salon central pour traçabilité
                embed_log_ai = discord.Embed(description=ai_reply_text, color=discord.Color.blue(), timestamp=datetime.now())
                embed_log_ai.set_author(name="Bot (Réponse IA)", icon_url=bot.user.display_avatar.url)
                await ticket_channel.send(embed=embed_log_ai)

            except Exception as e:
                print(f"Erreur IA Gemini : {e}")
                await message.channel.send("✅ Votre message a bien été transmis à l'équipe d'administration.")

    # 2. Réponse de la Centrale vers l'utilisateur en MP
    elif message.guild and message.guild.id == CENTRAL_GUILD_ID:
        if message.channel.category and message.channel.category.name == "📩 ── [ TICKETS MP ] ──":
            if message.content.startswith("/") or message.content.startswith("!"):
                await bot.process_commands(message)
                return
            if message.channel.id in paused_tickets:
                return

            # Dès qu'un administrateur humain écrit dans le salon, on désactive l'IA pour ce ticket
            if message.channel.id in ai_handled_tickets:
                ai_handled_tickets.remove(message.channel.id)
                await message.channel.send("🛡️ *[Mode IA désactivé : un administrateur a pris le relais en manuel]*")

            if message.channel.topic and "ID_USER:" in message.channel.topic:
                user_id = int(message.channel.topic.split("ID_USER:")[1].strip())
                user = bot.get_user(user_id)
                if user:
                    try:
                        embed_reply = discord.Embed(
                            title="💬 Réponse du Support",
                            description=message.content,
                            color=discord.Color.green(),
                            timestamp=datetime.now()
                        )
                        embed_reply.set_footer(
                            text=f"🛡️ Réponse de l'administrateur : {message.author.display_name}",
                            icon_url=message.author.display_avatar.url
                        )
                        if message.attachments:
                            embed_reply.set_image(url=message.attachments[0].url)
                        
                        await user.send(embed=embed_reply)
                        await message.add_reaction("✅")
                    except Exception:
                        await message.channel.send("❌ Impossible d'envoyer le MP à l'utilisateur.")

    await bot.process_commands(message)

# =========================================================================
# ⚙️ COMMANDES SLASH DE MODÉRATION ET D'ADMINISTRATION GLOBALE
# =========================================================================

@bot.tree.command(name="global-ban", description="Bannit un utilisateur de TOUS les serveurs du réseau avec notification MP.")
@app_commands.describe(user_id="ID de l'utilisateur à bannir", raison="Raison du bannissement global")
async def global_ban(interaction: discord.Interaction, user_id: str, raison: str):
    if interaction.guild_id != CENTRAL_GUILD_ID:
        await interaction.response.send_message("❌ Cette commande est réservée au serveur central.", ephemeral=True)
        return

    await interaction.response.defer()
    target_id = int(user_id)
    user_to_ban = await bot.fetch_user(target_id)
    
    if not user_to_ban:
        await interaction.followup.send("❌ Utilisateur introuvable.")
        return

    mp_status = "Envoyé avec succès"
    try:
        embed_mp = discord.Embed(
            title="🔨 BANNISSEMENT GLOBAL DU RÉSEAU",
            description=f"Vous avez été banni de l'ensemble des serveurs gérés par l'administration centralisée.\n\n"
                        f"**Raison :** {raison}\n"
                        f"**Opérateur :** {interaction.user.name}",
            color=discord.Color.dark_red(),
            timestamp=datetime.now()
        )
        embed_mp.set_footer(text="🛡️ Sanction globale du réseau")
        await user_to_ban.send(embed=embed_mp)
    except Exception:
        mp_status = "Échec (MP fermés ou utilisateur non joignable)"

    banned_guilds = []
    failed_guilds = []

    for guild in bot.guilds:
        if guild.id == CENTRAL_GUILD_ID:
            continue
        try:
            await guild.ban(user_to_ban, reason=f"[GLOBAL-BAN par {interaction.user}] : {raison}")
            banned_guilds.append(guild.name)
        except Exception:
            failed_guilds.append(guild.name)

    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if central_guild:
        for ch in central_guild.text_channels:
            if "sanctions-globales" in ch.name:
                embed_log = discord.Embed(
                    title="🔨 SANCTION GLOBALE : BAN",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                embed_log.add_field(name="👤 Utilisateur Sanctionné", value=f"{user_to_ban.mention} (`{user_to_ban.id}`)", inline=False)
                embed_log.add_field(name="🛡️ Administrateur", value=f"{interaction.user.mention}", inline=False)
                embed_log.add_field(name="📝 Raison", value=raison, inline=False)
                embed_log.add_field(name="📩 Notification MP", value=mp_status, inline=False)
                embed_log.add_field(name="✅ Banni de", value=", ".join(banned_guilds) if banned_guilds else "Aucun", inline=False)
                if failed_guilds:
                    embed_log.add_field(name="⚠️ Échecs", value=", ".join(failed_guilds), inline=False)
                await ch.send(embed=embed_log)
                break

    await interaction.followup.send(f"✅ Bannissement global exécuté pour **{user_to_ban}**. (`{len(banned_guilds)}` serveurs affectés)")

@bot.tree.command(name="global-kick", description="Expulse un utilisateur de TOUS les serveurs du réseau avec notification MP.")
@app_commands.describe(user_id="ID de l'utilisateur à expulser", raison="Raison de l'expulsion globale")
async def global_kick(interaction: discord.Interaction, user_id: str, raison: str):
    if interaction.guild_id != CENTRAL_GUILD_ID:
        await interaction.response.send_message("❌ Cette commande est réservée au serveur central.", ephemeral=True)
        return

    await interaction.response.defer()
    target_id = int(user_id)
    user_to_kick = await bot.fetch_user(target_id)
    
    if not user_to_kick:
        await interaction.followup.send("❌ Utilisateur introuvable.")
        return

    mp_status = "Envoyé avec succès"
    try:
        embed_mp = discord.Embed(
            title="🚪 EXPULSION GLOBALE DU RÉSEAU",
            description=f"Vous avez été expulsé de l'ensemble des serveurs gérés par l'administration centralisée.\n\n"
                        f"**Raison :** {raison}\n"
                        f"**Opérateur :** {interaction.user.name}",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        embed_mp.set_footer(text="🛡️ Sanction globale du réseau")
        await user_to_kick.send(embed=embed_mp)
    except Exception:
        mp_status = "Échec (MP fermés ou utilisateur non joignable)"

    kicked_guilds = []
    failed_guilds = []

    for guild in bot.guilds:
        if guild.id == CENTRAL_GUILD_ID:
            continue
        member = guild.get_member(target_id)
        if member:
            try:
                await member.kick(reason=f"[GLOBAL-KICK par {interaction.user}] : {raison}")
                kicked_guilds.append(guild.name)
            except Exception:
                failed_guilds.append(guild.name)

    central_guild = bot.get_guild(CENTRAL_GUILD_ID)
    if central_guild:
        for ch in central_guild.text_channels:
            if "sanctions-globales" in ch.name:
                embed_log = discord.Embed(
                    title="🚪 SANCTION GLOBALE : KICK",
                    color=discord.Color.orange(),
                    timestamp=datetime.now()
                )
                embed_log.add_field(name="👤 Utilisateur Sanctionné", value=f"{user_to_kick.mention} (`{user_to_kick.id}`)", inline=False)
                embed_log.add_field(name="🛡️ Administrateur", value=f"{interaction.user.mention}", inline=False)
                embed_log.add_field(name="📝 Raison", value=raison, inline=False)
                embed_log.add_field(name="📩 Notification MP", value=mp_status, inline=False)
                embed_log.add_field(name="✅ Expulsé de", value=", ".join(kicked_guilds) if kicked_guilds else "Aucun", inline=False)
                if failed_guilds:
                    embed_log.add_field(name="⚠️ Échecs", value=", ".join(failed_guilds), inline=False)
                await ch.send(embed=embed_log)
                break

    await interaction.followup.send(f"✅ Expulsion globale exécutée pour **{user_to_kick}**. (`{len(kicked_guilds)}` serveurs affectés)")

@bot.tree.command(name="stats-reseau", description="Affiche l'état global et les statistiques de l'infrastructure.")
async def stats_reseau(interaction: discord.Interaction):
    if interaction.guild_id != CENTRAL_GUILD_ID:
        await interaction.response.send_message("❌ Cette commande est réservée au serveur central.", ephemeral=True)
        return

    total_guilds = len(bot.guilds) - 1
    total_members = sum(g.member_count for g in bot.guilds if g.id != CENTRAL_GUILD_ID)
    total_channels = sum(len(g.channels) for g in bot.guilds if g.id != CENTRAL_GUILD_ID)

    embed_stats = discord.Embed(
        title="📊 STATISTIQUES GLOBALES DU RÉSEAU",
        description="Vue d'ensemble de l'infrastructure sous le contrôle du bot master.",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    embed_stats.set_thumbnail(url=bot.user.display_avatar.url)
    embed_stats.add_field(name="🌐 Serveurs Clients", value=f"`{total_guilds}` serveur(s)", inline=True)
    embed_stats.add_field(name="👥 Membres Cumulés", value=f"`{total_members}` membre(s)", inline=True)
    embed_stats.add_field(name="📁 Salons Surveillés", value=f"`{total_channels}` salon(s)", inline=True)
    embed_stats.add_field(name="🔒 Serveurs Confinés", value=f"`{len(locked_down_servers)}` serveur(s)", inline=True)
    embed_stats.add_field(name="🚫 Utilisateurs Bloqués MP", value=f"`{len(blocked_users)}` utilisateur(s)", inline=True)
    embed_stats.set_footer(text=f"Bot actif • Latence : {round(bot.latency * 1000)}ms")

    await interaction.response.send_message(embed=embed_stats)

@bot.tree.command(name="diffuser", description="Diffuse un message officiel sur tous les serveurs clients.")
@app_commands.describe(titre="Titre de l'annonce", message="Contenu de l'annonce")
async def diffuser(interaction: discord.Interaction, titre: str, message: str):
    if interaction.guild_id != CENTRAL_GUILD_ID:
        await interaction.response.send_message("❌ Cette commande est réservée au serveur central.", ephemeral=True)
        return

    await interaction.response.defer()
    sent_guilds = []
    failed_guilds = []

    embed_announcement = discord.Embed(
        title=f"📢 {titre}",
        description=message,
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    embed_announcement.set_footer(text=f"Annonce officielle transmise par l'Administration Centralisée")

    for guild in bot.guilds:
        if guild.id == CENTRAL_GUILD_ID:
            continue
        
        target_channel = guild.system_channel
        if not target_channel:
            for ch in guild.text_channels:
                if "annonce" in ch.name or "general" in ch.name or "général" in ch.name:
                    target_channel = ch
                    break
            if not target_channel and guild.text_channels:
                target_channel = guild.text_channels[0]

        if target_channel:
            try:
                await target_channel.send(embed=embed_announcement)
                sent_guilds.append(guild.name)
            except Exception:
                failed_guilds.append(guild.name)
        else:
            failed_guilds.append(guild.name)

    await interaction.followup.send(
        f"📢 **Diffusion terminée !**\n"
        f"✅ Transmis à **{len(sent_guilds)}** serveur(s) : {', '.join(sent_guilds) if sent_guilds else 'Aucun'}\n"
        f"⚠️ Échecs sur **{len(failed_guilds)}** serveur(s)"
    )

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

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
        
    embed = discord.Embed(
        title="🗑️ Message Supprimé", 
        description=f"Message de **{message.author.mention}** (`{message.author}`) supprimé dans {message.channel.mention}.", 
        color=discord.Color.red(),
        timestamp=datetime.now()
    )
    
    content = message.content if message.content else "*[Aucun texte / Uniquement un média, une image ou un embed]*"
    if len(content) > 1024:
        content = content[:1021] + "..."
        
    embed.add_field(name="📝 Contenu du message", value=content, inline=False)
    
    if message.attachments:
        embed.set_image(url=message.attachments[0].url)
        
    embed.set_footer(text=f"Serveur : {message.guild.name} • ID Auteur : {message.author.id}")
    await send_central_log(message.guild.id, "messages", embed)

# =========================================================================
# 🏗️ CRÉATION AUTOMATIQUE DES SALONS ET FICHE INFO DU SERVEUR CLIENT
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
    embed = discord.Embed(title="🔨 Banni Localement", description=f"**{user}** a été banni du serveur local.", color=discord.Color.dark_red())
    await send_central_log(guild.id, "sanctions", embed)

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
