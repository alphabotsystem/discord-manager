source /run/secrets/alpha-service/key
if [[ $PRODUCTION_MODE == "1" ]]
then
	python app/discord_manager.py
else
	python -u app/discord_manager.py
fi