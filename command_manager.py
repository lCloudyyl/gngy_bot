import discord
import json
import os
from discord import app_commands
from discord.ext import commands

config_path = "config.json"

SETTINGS = {
    "INT": {"max_history", "word_threshold", "set_channel"},
    "BOOL": {"threads", "statistics", "display_model", "safety"},
    "STR": {"image_model", "text_model"},
}
ALL_OPTIONS = sorted(list(SETTINGS["INT"] | SETTINGS["BOOL"] | SETTINGS["STR"]))
class DB_Manager:
    def __init__(self, path: str = config_path):
        self.path = path

    def ensure_guild(self, data, guild_id: int):
        if "Guilds" not in data:
            data["Guilds"] = {}
        gid = str(guild_id)
        if gid not in data["Guilds"]:
            data["Guilds"][gid] = self._default_guild()
        return data["Guilds"][gid]

    def _default_data(self):
        return {
            "Guilds": {}
        }

    def _default_guild(self):
        return {
            "max_history": 10,
            "word_threshold": 500,
            "set_channel": None,
            "threads": False,
            "statistics": False,
            "display_model": True,
            "safety": False,
            "image_model": "gemini-2.0-flash-preview-image-generation",
            "text_model": "gemini-2.0-flash"
        }

    def file_exists(self):
        if not os.path.exists(self.path):
            data = self._default_data()
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)

    def data_read(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            self.file_exists()
            return self._default_data()
        except json.JSONDecodeError:
            return self._default_data()


    def data_write(self, data):
        try:
            directory = os.path.dirname(self.path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
                return True

        except (json.JSONDecodeError, FileNotFoundError):
            if os.path.exists(self.path):
                os.rename(self.path, f"{self.path}.backup")
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self._default_data(), f, indent=4)
            return False

        except Exception as e:
            print(f"Err: {e}")
            return False
class Discord_Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tree = bot.tree
        self.db_manager = DB_Manager()

    async def config_option_autocomplete(self, interaction: discord.Interaction, current: str):
        current_l = (current or "").lower()
        choices = [app_commands.Choice(name=o, value=o) for o in ALL_OPTIONS if current_l in o.lower()]
        return choices[:25]

    @app_commands.command(name="config", description="Edit server config")
    @app_commands.describe(option="Setting", value="New value")
    @app_commands.autocomplete(option=config_option_autocomplete)
    async def config_edit(self, interaction: discord.Interaction, option: str, value: str):
        await interaction.response.send_message(f"{interaction.user.mention} Editing config...")
        guild_id = interaction.guild.id if interaction.guild else 0
        data = self.db_manager.data_read()
        cfg = self.db_manager.ensure_guild(data, guild_id)

        print(option, value)
        try:
            if option in SETTINGS["INT"]:
                cfg[option] = max(0, int(value))

            elif option in SETTINGS["BOOL"]:
                cfg[option] = value.lower() in ("1", "true", "yes", "on")
            
            elif option in SETTINGS["STR"]:
                cfg[option] = value
            else:
                await interaction.followup.send("Unknown setting.")
                return
        except ValueError:
            await interaction.followup.send(f"Invalid value for {option}.")
            return
        except Exception as e:
            await interaction.followup.send(f"Error: {e}.")
            return

        self.db_manager.data_write(data)
        await interaction.followup.send(f"Updated {option}.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Discord_Commands(bot))

'''
/config option: 
max_history number 
message length number 
set channel number 

threads for long messages bool
statistics bool 
display model used on message bool
safety enable bool

image_model model 
text_model model  


number
bool
model
'''



