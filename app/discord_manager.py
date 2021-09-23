from os import environ
from datetime import datetime
from datetime import timedelta
from pytz import utc
from asyncio import CancelledError, InvalidStateError, TimeoutError, sleep, all_tasks, wait_for
from traceback import format_exc

import discord
from google.cloud.firestore import AsyncClient as FirestoreAsyncClient
from google.cloud.error_reporting import Client as ErrorReportingClient

from DatabaseConnector import DatabaseConnector

from helpers.utils import Utils


database = FirestoreAsyncClient()


class Alpha(discord.AutoShardedClient):
	accountProperties = DatabaseConnector(mode="account")

	def prepare(self):
		self.logging = ErrorReportingClient(service="discord_manager")

	async def on_ready(self):
		t = datetime.now().astimezone(utc)

		self.alphaGuild = client.get_guild(414498292655980583)
		self.proRoles = [
			discord.utils.get(self.alphaGuild.roles, id=484387309303758848), # Alpha Pro role
			discord.utils.get(self.alphaGuild.roles, id=593768473277104148), # Ichibot role
			discord.utils.get(self.alphaGuild.roles, id=647824289923334155), # Registered role
			discord.utils.get(self.alphaGuild.roles, id=601524236464553984)  # Beta tester role
		]

		await self.update_system_status(t)
		await self.update_static_messages()

		print("[Startup]: Alpha Manager is online")

	async def update_static_messages(self):
		if not environ["PRODUCTION_MODE"]: return
		try:
			faqAndRulesChannel = client.get_channel(601160698310950914)
			guildRulesMessage = await faqAndRulesChannel.fetch_message(850729258049601556)
			termsOfServiceMessage = await faqAndRulesChannel.fetch_message(850729261216301086)
			faqMessage = await faqAndRulesChannel.fetch_message(850731156391329793)
			if guildRulesMessage is not None: await guildRulesMessage.edit(content=None, embed=discord.Embed(title="All members of this official Alpha community must follow the community rules. Failure to do so will result in a warning, kick, or ban, based on our sole discretion.", description="[Community rules](https://www.alphabotsystem.com/community-rules) (last modified on January 31, 2020).", color=0x673AB7), suppress=False)
			if termsOfServiceMessage is not None: await termsOfServiceMessage.edit(content=None, embed=discord.Embed(title="By using Alpha branded services you agree to our Terms of Service and Privacy Policy. You can read them on our website.", description="[Terms of Service](https://www.alphabotsystem.com/terms-of-service) (last modified on March 6, 2020)\n[Privacy Policy](https://www.alphabotsystem.com/privacy-policy) (last modified on January 31, 2020).", color=0x673AB7), suppress=False)
			if faqMessage is not None: await faqMessage.edit(content=None, embed=discord.Embed(title="If you have any questions, refer to our FAQ section, guide, or ask for help in support channels.", description="[Frequently Asked Questions](https://www.alphabotsystem.com/faq)\n[Feature overview with examples](https://www.alphabotsystem.com/guide)\nFor other questions, use <#574196284215525386>.", color=0x673AB7), suppress=False)

			ichibotChannel = client.get_channel(825460988660023326)
			howtoMessage = await ichibotChannel.fetch_message(850764390290030603)
			if howtoMessage is not None: await howtoMessage.edit(content=None, embed=discord.Embed(title="Best-in-class order execution client. Trade cryptocurrencies via Ichibot right in Discord.", description="[Sign up for a free account on our website](https://www.alphabotsystem.com/sign-up). If you already signed up, [sign in](https://www.alphabotsystem.com/sign-in), connect your account with your Discord profile, and add an API key. All Ichibot commands are prefixed with `x`. Learn more about Ichibot on their [GitLab page](https://www.alphabotsystem.com/guide/ichibot).", color=0x673AB7), suppress=False)

		except CancelledError: pass
		except Exception:
			print(format_exc())
			if environ["PRODUCTION_MODE"]: self.logging.report_exception()

	async def on_member_join(self, member):
		await self.update_alpha_guild_roles(only=member.id)

	async def update_alpha_guild_roles(self, only=None):
		try:
			if not await self.accountProperties.check_status(): return
			accounts = await self.accountProperties.keys()
			matches = {value: key for key, value in accounts.items()}

			for member in self.alphaGuild.members:
				if only is not None and only != member.id: continue

				accountId = matches.get(str(member.id))

				if accountId is not None:
					await sleep(0.4)
					properties = await self.accountProperties.get(accountId)
					if properties is None: continue

					if self.proRoles[2] not in member.roles:
						try: await member.add_roles(self.proRoles[2])
						except: pass

					if len(properties["apiKeys"].keys()) != 0:
						if self.proRoles[1] not in member.roles:
							try: await member.add_roles(self.proRoles[1])
							except: pass
					elif self.proRoles[1] in member.roles:
						try: await member.remove_roles(self.proRoles[1])
						except: pass

					if properties["customer"]["personalSubscription"].get("plan", "free") != "free":
						if self.proRoles[0] not in member.roles:
							await member.add_roles(self.proRoles[0])
					elif self.proRoles[0] in member.roles:
						try: await member.remove_roles(self.proRoles[0])
						except: pass

				elif self.proRoles[0] in member.roles or self.proRoles[2] in member.roles:
					await sleep(0.4)
					try: await member.remove_roles(self.proRoles[0], self.proRoles[2])
					except: pass

		except CancelledError: pass
		except Exception:
			print(format_exc())
			if environ["PRODUCTION_MODE"]: self.logging.report_exception()

	# -------------------------
	# Job queue
	# -------------------------

	async def job_queue(self):
		while True:
			try:
				await sleep(Utils.seconds_until_cycle())
				t = datetime.now().astimezone(utc)
				timeframes = Utils.get_accepted_timeframes(t)

				if "1m" in timeframes:
					await self.update_system_status(t)
				if "15m" in timeframes:
					client.loop.create_task(self.update_alpha_guild_roles())
			except CancelledError: return
			except Exception:
				print(format_exc())
				if environ["PRODUCTION_MODE"]: self.logging.report_exception()

	async def update_system_status(self, t):
		try:
			statistics = await database.document("discord/statistics").get()
			statistics = statistics.to_dict()["{}-{:02d}".format(t.year, t.month)]
			t2 = t + timedelta(minutes=5)
			if t2.month != t.month:
				await database.document("discord/statistics").set({"{}-{:02d}".format(t2.year, t2.month): statistics}, merge=True)

			numOfCharts = ":chart_with_upwards_trend: {:,} charts requested".format(statistics["c"] + statistics["hmap"])
			numOfAlerts = ":bell: {:,} alerts set".format(statistics["alerts"])
			numOfPrices = ":money_with_wings: {:,} prices & details pulled".format(statistics["d"] + statistics["p"] + statistics["v"] + statistics["mcap"] + statistics["mk"] + statistics["convert"])
			numOfTrades = ":dart: {:,} trades executed".format(statistics["paper"] + statistics["x"])
			numOfGuilds = ":heart: Used in {:,} Discord communities".format(statistics["servers"])

			statisticsEmbed = discord.Embed(title="{}\n{}\n{}\n{}\n{}".format(numOfCharts, numOfAlerts, numOfPrices, numOfTrades, numOfGuilds), color=0x673AB7)

			if environ["PRODUCTION_MODE"]:
				statusChannel = client.get_channel(560884869899485233)
				statsMessage = await statusChannel.fetch_message(850729112321392640)
				if statsMessage is not None:
					await statsMessage.edit(content=None, embed=statisticsEmbed, suppress=False)

		except CancelledError: pass
		except Exception:
			print(format_exc())
			if environ["PRODUCTION_MODE"]: self.logging.report_exception()


	# -------------------------
	# Message handling
	# -------------------------

	async def on_message(self, message):
		try:
			if message.author.id != 361916376069439490: return
			if message.clean_content.lower().startswith("beta "):
				parameters = message.clean_content.split(" ")[1:]
				if len(parameters) == 2:
					ch = client.get_channel(int(parameters[0]))
					me = await ch.fetch_message(int(parameters[1]))
					reactions = me.reactions
					for reaction in reactions:
						async for user in reaction.users():
							try:
								if self.proRoles[3] not in user.roles: await user.add_roles(self.proRoles[3])
							except:
								pass
					await message.delete()
		except CancelledError: pass
		except Exception:
			print(format_exc())
			if environ["PRODUCTION_MODE"]: self.logging.report_exception()

# -------------------------
# Initialization
# -------------------------

def handle_exit(sleepDuration=0):
	print("\n[Shutdown]: closing tasks")
	try: client.loop.run_until_complete(client.close())
	except: pass
	for t in all_tasks(loop=client.loop):
		if t.done():
			try: t.exception()
			except InvalidStateError: pass
			except TimeoutError: pass
			except CancelledError: pass
			continue
		t.cancel()
		try:
			client.loop.run_until_complete(wait_for(t, 5, loop=client.loop))
			t.exception()
		except InvalidStateError: pass
		except TimeoutError: pass
		except CancelledError: pass
	from time import sleep as ssleep
	ssleep(sleepDuration)

if __name__ == "__main__":
	environ["PRODUCTION_MODE"] = environ["PRODUCTION_MODE"] if "PRODUCTION_MODE" in environ and environ["PRODUCTION_MODE"] else ""
	print("[Startup]: Alpha Manager is in startup, running in {} mode.".format("production" if environ["PRODUCTION_MODE"] else "development"))

	intents = discord.Intents.all()

	client = Alpha(intents=intents, status=discord.Status.invisible)
	print("[Startup]: object initialization complete")
	client.prepare()

	while True:
		client.loop.create_task(client.job_queue())
		try:
			token = environ["DISCORD_MANAGER_TOKEN"]
			client.loop.run_until_complete(client.start(token))
		except (KeyboardInterrupt, SystemExit):
			handle_exit()
			client.loop.close()
			break
		except Exception:
			print(format_exc())
			handle_exit(sleepDuration=900)

		client = Alpha(loop=client.loop, status=discord.Status.invisible)