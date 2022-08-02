from os import environ
environ["PRODUCTION_MODE"] = environ["PRODUCTION_MODE"] if "PRODUCTION_MODE" in environ and environ["PRODUCTION_MODE"] else ""

from time import time
from random import randint
from datetime import datetime, timedelta
from pytz import utc
from asyncio import CancelledError, sleep
from traceback import format_exc

from discord import Client, Embed, Intents, Status
from discord.ext import tasks
from discord.utils import get as getFromDiscord
from google.cloud.firestore import AsyncClient as FirestoreAsyncClient
from google.cloud.error_reporting import Client as ErrorReportingClient

from helpers.utils import Utils

from DatabaseConnector import DatabaseConnector


database = FirestoreAsyncClient()
logging = ErrorReportingClient(service="discord_manager")


# -------------------------
# Initialization
# -------------------------

intents = Intents.all()

bot = Client(intents=intents, status=Status.invisible, activity=None)


# -------------------------
# Member events
# -------------------------

@bot.event
async def on_member_join(member):
	await update_alpha_guild_roles(only=member.id)

@tasks.loop(minutes=15.0)
async def update_alpha_guild_roles(only=None):
	try:
		if not await accountProperties.check_status(): return
		accounts = await accountProperties.keys()
		matches = {value: key for key, value in accounts.items()}

		for member in alphaGuild.members:
			if only is not None and only != member.id: continue

			accountId = matches.get(str(member.id))

			if accountId is not None:
				await sleep(0.4)
				properties = await accountProperties.get(accountId)
				if properties is None: continue

				if proRoles[2] not in member.roles:
					try: await member.add_roles(proRoles[2])
					except: pass

				if len(properties["apiKeys"].keys()) != 0:
					if proRoles[1] not in member.roles:
						try: await member.add_roles(proRoles[1])
						except: pass
				elif proRoles[1] in member.roles:
					try: await member.remove_roles(proRoles[1])
					except: pass

				if len(properties["customer"].get("subscriptions", {}).keys()) > 0:
					if proRoles[0] not in member.roles:
						await member.add_roles(proRoles[0])
				elif proRoles[0] in member.roles:
					try: await member.remove_roles(proRoles[0])
					except: pass

			elif proRoles[0] in member.roles or proRoles[2] in member.roles:
				await sleep(0.4)
				try: await member.remove_roles(proRoles[0], proRoles[2])
				except: pass

	except CancelledError: pass
	except Exception:
		print(format_exc())
		if environ["PRODUCTION_MODE"]: logging.report_exception()


# -------------------------
# Job functions
# -------------------------

@tasks.loop(minutes=1.0)
async def update_system_status():
	try:
		t = datetime.now().astimezone(utc)
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
	except Exception:
		print(format_exc())
		if environ["PRODUCTION_MODE"]: logging.report_exception()
	updatingNickname = False


# -------------------------
# Startup
# -------------------------

accountProperties = DatabaseConnector(mode="account")
alphaGuild = None
proRoles = None

@bot.event
async def on_ready():
	global alphaGuild, proRoles

	alphaGuild = bot.get_guild(414498292655980583)
	proRoles = [
		getFromDiscord(alphaGuild.roles, id=484387309303758848), # Alpha Pro role
		getFromDiscord(alphaGuild.roles, id=593768473277104148), # Ichibot role
		getFromDiscord(alphaGuild.roles, id=647824289923334155), # Registered role
		getFromDiscord(alphaGuild.roles, id=601524236464553984)  # Beta tester role
	]

	await update_system_status()
	await update_static_messages()

	if not update_alpha_guild_roles.is_running():
		update_alpha_guild_roles.start()
	if not update_system_status.is_running():
		update_system_status.start()

	print("[Startup]: Alpha Manager is online")

async def update_static_messages():
	if not environ["PRODUCTION_MODE"]: return
	try:
		ichibotChannel = bot.get_channel(825460988660023326)
		howtoMessage = await ichibotChannel.fetch_message(850764390290030603)
		if howtoMessage is not None: await howtoMessage.edit(content=None, embed=Embed(title="Best-in-class order execution client. Trade cryptocurrencies via Ichibot right in Discord.", description="[Sign up for a free account on our website](https://www.alphabotsystem.com/signup). If you already signed up, [sign in](https://www.alphabotsystem.com/login), connect your account with your Discord profile, and add an API key. All Ichibot commands are prefixed with `x`. Learn more about Ichibot on their [GitLab page](https://gitlab.com/Ichimikichiki/ichibot-client-app/-/wikis/home).", color=0x673AB7), suppress=False)

	except CancelledError: pass
	except Exception:
		print(format_exc())
		if environ["PRODUCTION_MODE"]: logging.report_exception()


# -------------------------
# Login
# -------------------------

bot.run(environ["DISCORD_MANAGER_TOKEN"])