import discord
import json
import os
import io 
from jsonschema import validate, ValidationError
from discord import app_commands
from discord.ext import commands

config_path = "config.json"

SETTINGS = {
    "INT": {"max_history", "word_threshold", "set_channel"},
    "BOOL": {"threads", "statistics", "display_model", "safety"},
    "STR": {"image_model", "text_model"},
}

config_schema = {
    "type": "object",
    "properties": {
    "max_history": {"type": "integer"},
    "word_threshold": {"type": "integer"},
    "set_channel": {"type": ["integer", "null"]},
    "threads": {"type": "boolean"},
    "statistics": {"type": "boolean"},
    "display_model": {"type": "boolean"},
    "safety": {"type": "boolean"},
    "image_model": {"type": "string"},
    "text_model": {"type": "string"}
    },
    "required": ["max_history", "word_threshold", "set_channel", "threads", "statistics", "display_model", "safety", "image_model", "text_model"]
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

class ConfirmationView(discord.ui.View):
    def __init__(self, *, timeout=60):
        super().__init__(timeout=timeout)
        self.result = None
        
    @discord.ui.button(label='✅ Confirm', style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('Confirmed!', ephemeral=True)
        self.result = True
        self.stop()
        
    @discord.ui.button(label='❌ Cancel', style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('Cancelled.', ephemeral=True)
        self.result = False
        self.stop()

async def get_confirmation(interaction: discord.Interaction, message: str, *, timeout=60) -> bool:
    """Get user confirmation with buttons. Returns True/False/None for timeout"""
    view = ConfirmationView(timeout=timeout)
    
    if interaction.response.is_done():
        await interaction.followup.send(message, view=view)
    else:
        await interaction.response.send_message(message, view=view)
    
    await view.wait()
    return view.result

class Discord_Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tree = bot.tree
        self.db_manager = DB_Manager()

    async def config_option_autocomplete(self, interaction: discord.Interaction, current: str):
        current_l = (current or "").lower()
        choices = [app_commands.Choice(name=o, value=o) for o in ALL_OPTIONS if current_l in o.lower()]
        return choices[:25]
    
    @app_commands.command(name="config_export", description="Download the current server config as JSON")
    async def config_export(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        data = self.db_manager.data_read()
        guild_id = str(interaction.guild.id)
        guild_cfg = data["Guilds"].get(guild_id, self.db_manager._default_guild())
        json_bytes = json.dumps(guild_cfg, indent=2).encode()

        file = discord.File(io.BytesIO(json_bytes), filename=f"{guild_id}_config.json")
        await interaction.followup.send(file=file, ephemeral=True)

    @app_commands.command(name="config_import", description="Upload a JSON file to overwrite the server config")
    async def config_import(self, interaction: discord.Interaction, attached: discord.Attachment):
        await interaction.response.defer(thinking=True, ephemeral=False)

        content = await attached.read()
        try:
            new_cfg = json.loads(content)
            validate(instance=new_cfg, schema=config_schema)

            confirmed = await get_confirmation(
                interaction, 
                "**Are you sure you want to import this config?**\n\n"
                "This action is **NOT reversible** and will overwrite all settings."
            )
            
            if confirmed is True:
                data = self.db_manager.data_read()
                data["Guilds"][str(interaction.guild.id)] = new_cfg
                self.db_manager.data_write(data)
                await interaction.followup.send("Config imported successfully.", ephemeral=True)
            elif confirmed is False:
                await interaction.followup.send("Import cancelled.")
            else:
                await interaction.followup.send("Confirmation timed out. Reset cancelled.")

        except ValidationError as ve:
            await interaction.followup.send(f"Invalid config format: {ve.message}", ephemeral=True)
        except json.JSONDecodeError:
            await interaction.followup.send("Failed to import. invalid JSON format.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Import failed: {str(e)}", ephemeral=True)

    @app_commands.command(name="config_edit", description="Edit server config")
    @app_commands.describe(option="Setting", value="New value")
    @app_commands.autocomplete(option=config_option_autocomplete)
    async def config_edit(self, interaction: discord.Interaction, option: str, value: str):
        await interaction.response.send_message(f"{interaction.user.mention} Editing config...")
        guild_id = interaction.guild.id if interaction.guild else 0
        data = self.db_manager.data_read()
        cfg = self.db_manager.ensure_guild(data, guild_id)

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

    @app_commands.command(name="config", description="Display current config")
    async def config_display(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=False)
        guild_id = interaction.guild.id if interaction.guild else 0
        data = self.db_manager.data_read()
        cfg = self.db_manager.ensure_guild(data, guild_id)

        embed = discord.Embed(title="Server Config:", color=0x00BFFF)

        for option in cfg:
            embed.add_field(
                name=f"{option}:",
                value=f"{cfg[option]}",
                inline=True
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="reset_config", description="Reset config for this server.")
    async def reset_config(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        guild_id = interaction.guild.id if interaction.guild else 0
        data = self.db_manager.data_read()
        
        if str(guild_id) not in data["Guilds"]:
            await interaction.followup.send("No config found for this server.")
            return
        
        confirmed = await get_confirmation(
            interaction, 
            "**Are you sure you want to reset config?**\n\n"
            "This action is **NOT reversible** and will restore all settings to defaults."
        )
        
        if confirmed is True:
            data["Guilds"][str(guild_id)] = self.db_manager._default_guild()
            self.db_manager.data_write(data)
            await interaction.followup.send("Config has been reset to defaults.")
        elif confirmed is False:
            await interaction.followup.send("Reset cancelled.")
        else:
            await interaction.followup.send("Confirmation timed out. Reset cancelled.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Discord_Commands(bot))