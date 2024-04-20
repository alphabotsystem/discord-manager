from os import environ
environ["PRODUCTION"] = environ["PRODUCTION"] if "PRODUCTION" in environ and environ["PRODUCTION"] else ""

from typing import Optional
from time import time
from random import randint
from datetime import datetime, timedelta, timezone
from asyncio import CancelledError, sleep, gather
from traceback import format_exc
from json import dumps
import aiohttp

from discord import app_commands, Client, Embed, ButtonStyle, Interaction, Member, Role, Intents, Status, ChannelType, PermissionOverwrite
from discord.ui import View, button, Button
from discord.ext import tasks
from discord.utils import get as getFromDiscord
from google.cloud.firestore import AsyncClient as FirestoreAsyncClient
from google.cloud.firestore import ArrayUnion
from google.cloud.error_reporting import Client as ErrorReportingClient

from DatabaseConnector import DatabaseConnector


database = FirestoreAsyncClient()
logging = ErrorReportingClient(service="discord_manager")


# -------------------------
# Initialization
# -------------------------

ALPHA_GUILD_ID = 414498292655980583

intents = Intents.all()
bot = Client(intents=intents, status=Status.invisible, activity=None)
tree = app_commands.CommandTree(bot)


# -------------------------
# Member events
# -------------------------

@bot.event
async def on_member_join(member):
	if member.guild.id == ALPHA_GUILD_ID:
		await update_alpha_guild_roles(only=member.id)

@tasks.loop(minutes=5.0)
async def update_alpha_guild_roles(only=None):
	if not environ["PRODUCTION"]: return
	start = time()
	try:
		if not await accountProperties.check_status(): return
		accounts = await accountProperties.keys()
		if len(accounts.keys()) == 0: return
		matches = {value: key for key, value in accounts.items()}

		for member in alphaGuild.members:
			if only is not None and only != member.id: continue

			accountId = matches.get(str(member.id))

			if accountId is not None:
				properties = await accountProperties.get(accountId)
				if properties is None: continue

				if cachedAlphaRoles[3] not in member.roles:
					try: await member.add_roles(cachedAlphaRoles[3])
					except: pass

				if len(properties["apiKeys"].keys()) != 0:
					if cachedAlphaRoles[2] not in member.roles:
						try: await member.add_roles(cachedAlphaRoles[2])
						except: pass
				elif cachedAlphaRoles[2] in member.roles:
					try: await member.remove_roles(cachedAlphaRoles[2])
					except: pass

				if len(properties["customer"].get("subscriptions", {}).keys()) > 0:
					if cachedAlphaRoles[0] not in member.roles:
						await member.add_roles(cachedAlphaRoles[0])
					if properties["customer"]["subscriptions"].get("botLicense", 0) > 0:
						await handle_bot_license_onboarding(member, accountId)
				elif cachedAlphaRoles[0] in member.roles:
					try: await member.remove_roles(cachedAlphaRoles[0])
					except: pass

			elif cachedAlphaRoles[0] in member.roles or cachedAlphaRoles[1] in member.roles or cachedAlphaRoles[3] in member.roles:
				try: await member.remove_roles(cachedAlphaRoles[0], cachedAlphaRoles[1], cachedAlphaRoles[3])
				except: pass

		await handle_bot_license_cancellations(accounts)

	except CancelledError: pass
	except:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()
	finally:
		print(f"Updated Alpha.bot roles in {round(time() - start, 2)} seconds.")

async def handle_bot_license_cancellations(accounts):
	for channel in alphaGuild.channels:
		if channel.type != ChannelType.text: continue
		if channel.category_id != 1041086360062263438: continue

		properties = await accountProperties.get(channel.topic)
		member = alphaGuild.get_member(int(accounts[channel.topic]))

		if properties["customer"]["subscriptions"].get("botLicense", 0) == 0:
			if member is not None and cachedAlphaRoles[1] in member.roles:
				await member.remove_roles(cachedAlphaRoles[1])
			await channel.send(content="Customer has canceled the subscription.")

async def handle_bot_license_onboarding(member, accountId):
	if cachedAlphaRoles[1] not in member.roles:
		await member.add_roles(cachedAlphaRoles[1])

	for channel in alphaGuild.channels:
		if channel.type != ChannelType.text: continue
		if channel.category_id != 1041086360062263438: continue
		if channel.topic == accountId: return

	categoryChannel = alphaGuild.get_channel(1041086360062263438)
	newChannel = await alphaGuild.create_text_channel(
		name=f"{member.name}-license",
		topic=accountId,
		category=categoryChannel,
		overwrites={
			alphaGuild.default_role: PermissionOverwrite(read_messages=False),
			cachedAlphaRoles[1]: PermissionOverwrite(read_messages=False),
			member: PermissionOverwrite(read_messages=True, send_messages=True)
		}
	)
	await newChannel.send(
		content=member.mention,
		embed=Embed(
			title="Thank you for purchasing a bot license. Let's begin!",
			description="To begin with the setup, please create a new bot in the [Discord Developer Portal](https://discord.com/developers/applications), and send over the token in this channel. You can find your bot's token in the `bot` tab in the portal by clicking the `reset token` button. We can set up a bot user for you as well, in which case you have to provide a name and a profile picture.\n\nA team member will be with you as soon as possible to help you with further steps. We aim to respond and bring your bot online within 24 hours. We'll connect your bot with our hosting as soon as all the details are provided.",
			color=0x9C27B0
		)
	)


# -------------------------
# Job functions
# -------------------------

@tasks.loop(minutes=1.0)
async def update_system_status():
	try:
		t = datetime.now().astimezone(timezone.utc)
		statistics = await database.document("discord/statistics").get()
		statistics = statistics.to_dict()["{}-{:02d}".format(t.year, t.month)]
		t2 = t + timedelta(minutes=5)
		if t2.month != t.month:
			await database.document("discord/statistics").set({"{}-{:02d}".format(t2.year, t2.month): statistics}, merge=True)

		numOfCharts = ":chart_with_upwards_trend: {:,} charts requested".format(statistics["c"] + statistics["hmap"])
		numOfAlerts = ":bell: {:,} alerts set".format(statistics["alert"])
		numOfPrices = ":money_with_wings: {:,} prices & details pulled".format(statistics["d"] + statistics["p"] + statistics["v"] + statistics["info"] + statistics["mk"] + statistics["convert"])
		numOfTrades = ":dart: {:,} trades executed".format(statistics["paper"] + statistics["x"])
		numOfGuilds = ":heart: Used in {:,} Discord communities".format(statistics["servers"])

		statisticsEmbed = Embed(title=f"{numOfCharts}\n{numOfAlerts}\n{numOfPrices}\n{numOfTrades}\n{numOfGuilds}", color=0x673AB7)

		statusChannel = bot.get_channel(560884869899485233)
		statsMessage = await statusChannel.fetch_message(850729112321392640)
		if statsMessage is not None:
			await statsMessage.edit(content=None, embed=statisticsEmbed, suppress=False)

	except CancelledError: pass
	except:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()
	updatingNickname = False

@tasks.loop(hours=8.0)
async def update_nickname_review():
	channel = bot.get_channel(571786092077121536)
	await channel.purge(limit=None, check=lambda m: True)

	settings = await database.document("discord/settings").get()
	nicknames = settings.to_dict()["nicknames"]

	for guild, data in nicknames.items():
		if data["allowed"] is None:
			await channel.send(embed=Embed(title=f"{data['server name']} ({guild}): {data['nickname']}"), view=NicknameReview(guild, data['nickname']))


class NicknameReview(View):
	def __init__(self, guildId, nickname):
		super().__init__(timeout=None)
		self.guildId = guildId
		self.nickname = nickname

	@button(label="Allow", style=ButtonStyle.green)
	async def allow(self, interaction: Interaction, button: Button):
		await interaction.message.delete()
		await database.document("discord/settings").set({
			"nicknames": {
				self.guildId: {
					"allowed": True
				}
			}
		}, merge=True)

	@button(label="Deny", style=ButtonStyle.red)
	async def deny(self, interaction: Interaction, button: Button):
		await interaction.message.delete()
		await database.document("discord/settings").set({
			"nicknames": {
				self.guildId: {
					"allowed": False
				}
			}
		}, merge=True)

	@button(label="Global allow", style=ButtonStyle.blurple)
	async def deny(self, interaction: Interaction, button: Button):
		await interaction.message.delete()
		await database.document("discord/settings").update({
			"nicknameWhitelist": ArrayUnion([self.nickname])
		})

class PortalBeta(View):
	def __init__(self, role):
		self.role = role
		super().__init__(timeout=None)

	@button(label="I'm in", style=ButtonStyle.primary)
	async def allow(self, interaction: Interaction, button: Button):
		if interaction.user is not None:
			try: await interaction.user.add_roles(self.role)
			except: pass
		await interaction.response.send_message("You're in!", ephemeral=True)


# -------------------------
# Commands
# -------------------------

message = app_commands.Group(name="messages", description="Message management", guild_only=True)
beta = app_commands.Group(name="beta", description="Beta role management", guild_only=True)

@message.command(name="purge", description="Purge messages from a channel")
@app_commands.describe(
    limit="The number of messages to delete",
	user="The user to delete messages from"
)
async def purge_beta(interaction: Interaction, limit: Optional[int] = None, user: Optional[Member] = None):
	try:
		await interaction.response.defer(ephemeral=True)
		await interaction.channel.purge(limit=limit, check=lambda m: user is None or m.author == user)
		await interaction.followup.send(content="Done!", ephemeral=True)
	except:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()

@beta.command(name="purge", description="Remove the beta role from everyone")
@app_commands.describe(
	role="The beta role"
)
async def purge_beta(interaction: Interaction, role: Role):
	try:
		for member in alphaGuild.members:
			if role in member.roles:
				try: await member.remove_roles(role)
				except: pass
		await interaction.response.send_message(content="Done!", ephemeral=True)
	except:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()

@beta.command(name="portal", description="Open the portal to the beta role")
@app_commands.describe(
	role="The beta role"
)
async def portal_beta(interaction: Interaction, role: Role):
	try:
		await interaction.response.send_message(
			content="Hey there, want to test out something new?",
			view=PortalBeta(role)
		)
	except:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()

tree.add_command(message)
tree.add_command(beta)

@tree.context_menu(name="Show Details")
@app_commands.default_permissions(administrator=True)
async def show_details(interaction: Interaction, member: Member):
	[accountId, properties] = await gather(
		accountProperties.match(member.id),
		accountProperties.get(member.id)
	)

	if "customer" not in properties:
		await interaction.response.send_message(
			embed=Embed(title=f"No user info"),
			ephemeral=True
		)
		return

	subMap = {
		"advancedCharting": "Advanced Charting",
		"botLicense": "Bot License",
		"priceAlerts": "Price Alerts",
		"satellites": "Price Satellite Bots",
		"scheduledPosting": "Scheduled Posting",
		"tradingviewLayouts": "TradingView Layouts"
	}

	customer = properties.pop("customer")
	apiKeys = sorted(properties.pop("apiKeys").keys())
	subscriptions = [subMap.get(e, e) for e in sorted(customer["subscriptions"].keys())]

	if len(subscriptions) == 0:
		details = f"Account UID: ```{accountId}```\nStripe ID: ```{customer['stripeId']}```"

	else:
		slots = ""
		for sub, settings in customer['slots'].items():
			if len(settings.keys()) == 0:
				slots += f"{subMap.get(sub, sub)}: none\n"
			elif sub == "satellites":
				satellites = sorted([f"{k} ({len(v['added'])})" for k, v in settings.items()])
				slots += f"{subMap.get(sub, sub)}: ```{', '.join(satellites)}```\n"
			else:
				slots += f"{subMap.get(sub, sub)}: ```{', '.join(sorted(settings.keys()))}```\n"

		details = f"Account UID: ```{accountId}```\nStripe ID: ```{customer['stripeId']}```\nSubscriptions: ```{', '.join(subscriptions)}```\n{slots}"

	await interaction.response.send_message(
		embed=Embed(
			title=f"User details for {member.name}",
			description=details,
		),
		ephemeral=True
	)

@tree.context_menu(name="Refresh roles")
@app_commands.default_permissions(administrator=True)
async def refresh_roles(interaction: Interaction, member: Member):
	await update_alpha_guild_roles(only=member.id)
	await interaction.response.send_message(
		content=f"Roles for {member.name} have been refreshed.",
		ephemeral=True
	)


# -------------------------
# Instant help
# -------------------------

@bot.event
async def on_message(message):
	if message.author.id in BOTS:
		return

	if message.clean_content.startswith("/"):
		async with aiohttp.ClientSession() as session:
			async with session.get("https://storage.alpha.bot/Command.png") as resp:
				if resp.status != 200:
					await message.channel.send(
						content="Looks like you're trying to use slash commands. You're almost there, just type `/` in the chat and you'll see a list of commands you can use. When you want to execute a command, make sure Discord is displaying it in the chat box. For the full list of commands with examples, you can check out [our website](https://www.alpha.bot/features).",
						reference=message,
						mention_author=True
					)
				else:
					data = io.BytesIO(await resp.read())
					await message.channel.send(
						content="Looks like you're trying to use slash commands. You're almost there, just type `/` in the chat and you'll see a list of commands you can use. When you want to execute a command, make sure Discord is displaying it in the chat box. For the full list of commands with examples, you can check out [our website](https://www.alpha.bot/features).",
						file=discord.File(data, 'slash_commands.png'),
						reference=message,
						mention_author=True
					)

	elif "<@401328409499664394>" in message.content:
		await message.channel.send(content="<@361916376069439490>")

	elif "signal" in message.clean_content.lower() and len(message.clean_content) < 40:
		await message.channel.send(
			content="Hey there, it looks like you're looking for signals. We unfortunately don't provide signals, but you can check out the [our website](https://www.alpha.bot) for more information.",
			reference=message,
			mention_author=True
		)

	elif message.channel.id in TEST_CHANNELS:
		lastTime = lastHeadsup.get(message.channel.id, 0)
		lastHeadsup[message.channel.id] = time()

		if message.author.id == 361916376069439490:
			return
		if lastTime + 5 * 60 > time():
			return

		await message.channel.send(
			content="Hey there, this channel is intended for testing purposes. If you're looking for the documentation, check https://www.alpha.bot/features. If you're looking for help, you can use <#1019642541374705787>, or <#480464108794281994> if you just want to chat.",
			reference=message,
			mention_author=True
		)

	elif message.channel.id == 1113820312795086969:
		await message.channel.purge(limit=20, check=lambda m: m.author.id == bot.user.id)
		await message.channel.send(
			embed=Embed(
				title="Add NASDAQ halt alerts to your server!",
				description="To add NASDAQ halt alerts, visit your community settings on [our website](https://www.alpha.bot/communities) and add a webhook URL in the NASDAQ Trade Halt Alerts section.",
				image="https://storage.alpha.bot/HaltAlerts.png"
			)
		)

# -------------------------
# Startup
# -------------------------

accountProperties = DatabaseConnector(mode="account")
alphaGuild = None
cachedAlphaRoles = None

BOTS = [401328409499664394, 739420701211099178]
TEST_CHANNELS = [814143168996048936, 417784977841979402]
lastHeadsup = {}

@bot.event
async def on_ready():
	global alphaGuild, cachedAlphaRoles

	alphaGuild = bot.get_guild(ALPHA_GUILD_ID)
	cachedAlphaRoles = [
		getFromDiscord(alphaGuild.roles, id=484387309303758848),  # Subscriber role
		getFromDiscord(alphaGuild.roles, id=1041085930880127098), # Licensing role
		getFromDiscord(alphaGuild.roles, id=593768473277104148),  # Ichibot role
		getFromDiscord(alphaGuild.roles, id=647824289923334155),  # Registered role
	]

	await update_system_status()
	await update_static_messages()

	if not update_alpha_guild_roles.is_running():
		update_alpha_guild_roles.start()
	if not update_system_status.is_running():
		update_system_status.start()
	if not update_nickname_review.is_running():
		update_nickname_review.start()

	await tree.sync()

	print("[Startup]: Alpha.bot Manager is online")

async def update_static_messages():
	if not environ["PRODUCTION"]: return
	try:
		rulesAndTosChannel = bot.get_channel(601160698310950914)
		guildRulesMessage = await rulesAndTosChannel.fetch_message(850729258049601556)
		termsOfServiceMessage = await rulesAndTosChannel.fetch_message(850729261216301086)
		if guildRulesMessage is not None: await guildRulesMessage.edit(content=None, embed=Embed(title="All members of the official Alpha.bot community must follow all community rules. Failure to do so will result in a warning, kick, or ban, based on our sole discretion.", description="[Community rules](https://www.alpha.bot/community-rules) (last modified on July 1, 2023).", color=0x673AB7), suppress=False)
		if termsOfServiceMessage is not None: await termsOfServiceMessage.edit(content=None, embed=Embed(title="By using Alpha.bot branded services you agree to our Terms of Service and Privacy Policy. You can read them on our website.", description="[Terms of Service](https://www.alpha.bot/terms-of-service) (last modified on September 25, 2022)\n[Privacy Policy](https://www.alpha.bot/privacy-policy) (last modified on June 24, 2022).", color=0x673AB7), suppress=False)

	except CancelledError: pass
	except:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()


# -------------------------
# Login
# -------------------------

bot.run(environ["DISCORD_MANAGER_TOKEN"])