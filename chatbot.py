# discord imports
import discord
from discord.ext import commands
from discord import app_commands

# image management imports
from PIL import Image
from io import BytesIO 
import aiohttp

# Gemini imports
from google import genai
from google.genai import types
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch

# general imports
import os
import asyncio
import inspect
import re
from dotenv import load_dotenv
import json
from datetime import datetime
from typing import Dict, List, Optional

# env stuff
load_dotenv(dotenv_path='.env')
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API = os.getenv('GOOGLE_API_KEY')
client = genai.Client(api_key=GEMINI_API)
guild_id =  int(os.getenv('GUILD_ID'))
channel_id = int(os.getenv('CHANNEL_ID'))
max_history = int(os.getenv('MAX_HISTORY', '10'))
text_model = os.getenv("TEXT_MODEL", "gemini-2.0-flash")
image_model = os.getenv('IMAGE_MODEL', "gemini-2.0-flash-preview-image-generation")
MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', '500'))

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
    category=types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
]

class PromptManager:
    def __init__(self, json_path="prompts.json"):
        self.json_path = json_path
        self.prompts_data = self.load_prompts()

    def load_prompts(self):
        if not os.path.exists(self.json_path):
            default_data = {
                "active_prompt": "default",
                "prompts": {
                    "default": {
                        "name": "default",
                        "content": "",
                        "created_by": "Master",
                        "created_at": datetime.now().isoformat(),
                        "usage_count": 0,
                        "is_active": True
                    }
                },
                "usage_history": []
            }
            self.save_prompts(default_data)
            return default_data
        
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        except (json.JSONDecodeError, FileNotFoundError):
            if os.path.exists(self.json_path):
                os.rename(self.json_path, f"{self.json_path}.backup")
            return self.load_prompts()

    def save_prompts(self, data=None):
        if data is None:
            data = self.prompts_data
        
        try:
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)    

        except Exception as e:
            print(f"Error saving prompt: {e}")  

    def add_prompt(self, name, content, user_id):
        if name in self.prompts_data["prompts"]:
            raise Exception(f"Prompt '{name}' already exists...")

        self.prompts_data["prompts"][name] = {
            "name": name,
            "content": content,
            "created_by": user_id,
            "created_at": datetime.now().isoformat(),
            "usage_count": 0,
            "is_active": False
        }

        self.save_prompts()

    def get_active_prompt(self):
        active_name = self.prompts_data.get("active_prompt", "default")
        active_prompt = self.prompts_data["prompts"].get(active_name)

        if active_prompt:
            return active_prompt["content"]

        return self.prompts_data["prompts"]["default"]["content"]

    def set_active_prompt(self, name, user_id):
        if name not in self.prompts_data["prompts"]:
            return False
        
        old_active = self.prompts_data.get("active_prompt")
        if old_active in self.prompts_data["prompts"]:
            self.prompts_data["prompts"][old_active]["is_active"] = False

        self.prompts_data["active_prompt"] = name
        self.prompts_data["prompts"][name]["is_active"] = True
        self.prompts_data["prompts"][name]["usage_count"] += 1

        self.prompts_data["usage_history"].append({
            "prompt_name": name,
            "used_by": user_id,
            "used_at": datetime.now().isoformat()
        })

        if len(self.prompts_data["usage_history"]) > 100:
            self.prompts_data["usage_history"] = self.prompts_data["usage_history"][-100:]
        
        self.save_prompts()
        return True
    
    def get_all_prompts(self):
        prompts = []
        for prompt_data in self.prompts_data["prompts"].values():
            prompts.append(prompt_data.copy())
        return prompts
        
    def get_prompt_by_name(self, name):
        return self.prompts_data["prompts"].get(name)
    
    def delete_prompt(self, name, user_id):
        if name == "default":
            raise Exception("Cannot delete default prompt...")
        
        if name not in self.prompts_data["prompts"]:
            return False

        if self.prompts_data.get("active_prompt") == name:
            self.set_active_prompt("default", user_id)

        del self.prompts_data["prompts"][name]
        self.save_prompts()
        return True
    
    def get_recent_prompts(self, limit: int = 5):
        recent_usage = self.prompts_data["usage_history"][-limit:]
        recent_names = []
        
        for usage in reversed(recent_usage):
            if usage["prompt_name"] not in recent_names:
                recent_names.append(usage["prompt_name"])

        return recent_names[:limit]

class GeminiService():
    @staticmethod
    async def generate_text_response(prompt, message_history):
        try: 
            system_prompt = prompt_manager.get_active_prompt()

            response = client.models.generate_content(
                model=text_model,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt),
                    contents = [f"The users prompt: {prompt} \n \n Heres the last {max_history} message(s) in the channel for context: {message_history} "]
                )
            text = getattr(response, "text", None)
            if not text:
                return "Error occurred during response" + str(response._error)

            return response.text

        except Exception as e: 
            print(f"Exception: {e}")
            return f"Exception: {e}"

    @staticmethod
    async def generate_text_response_using_image(pil_image, prompt, message_history):
        try: 
            system_prompt = prompt_manager.get_active_prompt()

            response = client.models.generate_content(
                model=text_model,
                config=types.GenerateContentConfig(
                        system_instruction=system_prompt),
                contents=[pil_image, f"The users prompt: {prompt}\n \n Heres the last {max_history} message(s) in the channel for context: {message_history}" if prompt else f"What is in this image? Heres the last {max_history} message(s) in the channel for context: {message_history}"] 
                )
            
            if not response: 
                return f"Error occurred during response {response}"
            return response.text
        
        except Exception as e:
            print(f"Exception: {e}")
            return f"Exception: {e}"
        
    @staticmethod
    async def generate_image(prompt):
        try: 
            image_data = None
            caption = None

            response = client.models.generate_content(
                model=image_model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE'],
                safety_settings=SAFETY_SETTINGS
                ),
            )
            
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                        image_bytes = part.inline_data.data
                        image_data = BytesIO(image_bytes)
                        image_data.seek(0)
                    elif part.text:
                        caption = part.text.strip()

            if not image_data or not caption: 
                return None, "Error occurred during response - missing image or caption"
            
            return image_data, caption
        
        except Exception as e:
            return f"Exception: {e}"

    @staticmethod
    async def generate_search(prompt):
        google_search_tool = Tool(
            google_search = GoogleSearch()
        )

        try: 
            system_prompt = prompt_manager.get_active_prompt()

            response = client.models.generate_content(
                model=text_model,
                contents=[prompt],
                config=GenerateContentConfig(
                    tools=[google_search_tool],
                    response_modalities=["TEXT"],
                    system_instruction=system_prompt,
                )
            )

            full_response_text = []
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        full_response_text.append(part.text)

            if not full_response_text: 
                return f"Error occurred during response"
            
            return full_response_text
        except Exception as e:
            return f"Exception: {e}"

    @staticmethod  
    async def check_for_attachment(message):
        image_url = None

        if message.attachments:
            for attachment in message.attachments:
                if any(ext in attachment.filename.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    return attachment.url

        if message.embeds:
            for embed in message.embeds:
                image_url = embed.url or (embed.image and embed.image.url) or (embed.thumbnail and embed.thumbnail.url)            
                if image_url and (
                    any(ext in image_url.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']) or
                    any(service in image_url.lower() for service in ['tenor.com', 'giphy.com', 'gfycat.com'])
                ):
                    return image_url
        return None

    @staticmethod  
    async def download_image(url, timeout=10):
        try:
            timeout_config = aiohttp.ClientTimeout(total=timeout)

            async with aiohttp.ClientSession(timeout=timeout_config) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        print(f"Non-200 status code: {resp.status}")
                        return None

                    content_length = resp.headers.get('content-length')
                    if content_length:
                        print(f"Content length: {content_length} bytes")

                    image_bytes = await resp.read()

                    image_data = BytesIO(image_bytes)
                    image_data.seek(0)

                    return image_data 

        except Exception as e:
            print(f"Download error: {e}")
            return None

class DiscordService():
    @staticmethod
    async def send_response(message, response):
        if len(response) <= MAX_MESSAGE_LENGTH:
            await message.channel.send(response)
        else:
            if isinstance(message.channel, discord.Thread):
                await DiscordService.send_in_chunks(message.channel, response)
            else:
                await message.channel.send(f"Response is too long ({len(response)} chars), creating thread...")
                thread = await message.create_thread(
                    name=f"AI Response - {message.author.display_name}",
                    auto_archive_duration=60
                )
                await DiscordService.send_in_chunks(thread, response)

    @staticmethod
    async def get_attr_dict(obj):
        attrs = {}
        for attr in dir(obj):
            if attr.startswith("__"):
                continue
            try:
                value = getattr(obj, attr)
                if inspect.isroutine(value):
                    continue
                attrs[attr] = repr(value)
            except Exception as e:
                attrs[attr] = f"<ERROR: {e}>"
        return attrs

    @staticmethod
    async def send_interaction_response(interaction, response):
        if len(response) <= MAX_MESSAGE_LENGTH:
            await interaction.followup.send(response)
        else:
            if isinstance(interaction.channel, discord.Thread):
                await DiscordService.send_in_chunks(interaction.channel, response)
            else:
                response_message = await interaction.original_response()
                thread = await response_message.create_thread(
                    name=f"AI Response - {interaction.user.display_name}",
                    auto_archive_duration=60
                )
                await DiscordService.send_in_chunks(thread, response)

    @staticmethod
    async def send_in_chunks(channel, text, chunk_size=1900):
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            await channel.send(chunk)
            await asyncio.sleep(0.3)


@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

'''
@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        # Optional: clear all global commands (careful in prod)
        bot.tree.clear_commands(guild=None)  # clears staged global commands [2]
        # Then sync only to your dev guild for fast iteration
        if guild_id:
            test_guild = discord.Object(id=1361097793325760552)
            print(test_guild)
            await bot.tree.sync(guild=test_guild)  # instant guild sync [18]
        else:
            await bot.tree.sync()
        print("Synced commands")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
'''

@bot.tree.command(name="image", description="Generate an image")
@app_commands.describe(prompt="Describe the image")
async def generate_image_slash(interaction: discord.Interaction, prompt: str):
    await interaction.response.send_message(f"{interaction.user.mention} Generating image...")
    try: 
        image_data, caption = await GeminiService.generate_image(prompt)

        if image_data:
            discord_file = discord.File(fp=image_data, filename="gemini_image.png")

            if len(caption) <= MAX_MESSAGE_LENGTH:
                await interaction.followup.send(content=caption, file=discord_file)
            else:
                await interaction.followup.send(file=discord_file)
                await DiscordService.send_interaction_response(interaction, caption)
        else:
            await interaction.followup.send("couldn't generate an image for that prompt.")

    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")

@bot.tree.command(name="search", description="Use google search on gemini")
@app_commands.describe(prompt="Prompt for google search")
async def slash_search(interaction: discord.Interaction, prompt: str):
    # await interaction.response.defer(thinking=True)
    await interaction.response.send_message(f"{interaction.user.mention} Searching... (this can take from 5s-30m)")

    async with interaction.channel.typing():
        try:
            response = await GeminiService.generate_search(prompt)
            
            if isinstance(response, list):
                await DiscordService.send_interaction_response(interaction, "\n".join(response))
            else:
                await interaction.followup.send(response)

        except Exception as e:
            print(f"error: {e}")
            await interaction.followup.send(f"error: {e}")

async def prompt_name_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    all_prompts = prompt_manager.get_all_prompts()
    return [
        app_commands.Choice(name=p["name"], value=p["name"])
        for p in all_prompts
        if current.lower() in p["name"].lower()
    ][:25]

@bot.tree.command(name="prompt_create", description="Create a new system prompt")
@app_commands.describe(
    name="Name for the prompt (no spaces, use underscores)",
    content="The system prompt content"
)
async def create_prompt(interaction: discord.Interaction, name: str, content: str):
    await interaction.response.defer()

    if " " in name or len(name) > 50:
        await interaction.followup.send("❌ - Prompt name must not contain spaces, or be under 50 chars")
        return
    
    try:
        prompt_manager.add_prompt(name, content, str(interaction.user.id))
        await interaction.followup.send(f"✅ Created system prompt: **{name}**")
    except Exception as e:
        await interaction.followup.send(f"❌ Err: {e}")

@bot.tree.command(name="prompt_list", description="View all available system prompts")
async def list_prompts(interaction: discord.Interaction):
    await interaction.response.defer()
    
    prompts = prompt_manager.get_all_prompts()
    active_prompt_name = prompt_manager.prompts_data.get("active_prompt", "default")

    embed = discord.Embed(title="System Prompts:", color=0x00FF00)

    if not prompts:
        embed.description = "No prompts available"
    else:
        for prompt in prompts[:10]:
            status = "🟢 **ACTIVE**" if prompt["name"] == active_prompt_name else "⚪"

            created_date = datetime.fromisoformat(prompt["created_at"]).strftime("%m/%d/%y")

            embed.add_field(
                name=f"{status} `{prompt['name']}`",
                value=f"By: <@{prompt['created_by']}>\nUsed: {prompt['usage_count']} times\nCreated: {created_date}",
                inline=True
            )

    recent = prompt_manager.get_recent_prompts(3)
    if recent:
        embed.add_field(
            name="🕒 Recently Used",
            value=" → ".join([f"`{name}`" for name in recent]),
            inline=False
        )

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="prompt_switch", description="Switch to a different system prompt")
@app_commands.describe(name="Name of the prompt to switch to")
@app_commands.autocomplete(name=prompt_name_autocomplete)
async def switch_prompt(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    success = prompt_manager.set_active_prompt(name, str(interaction.user.id))
    if success:
        await interaction.followup.send(f"✅ Switched to prompt: **{name}**")
    else:
        available = list(prompt_manager.prompts_data["prompts"].keys())
        await interaction.followup.send(f"❌ - prompt '{name}' not found. \n Available: {', '.join(available)}")

@bot.tree.command(name="prompt_preview", description="Preview a system prompt")
@app_commands.describe(name="Name of the prompt to preview")
@app_commands.autocomplete(name=prompt_name_autocomplete)
async def preview_prompt(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    prompt = prompt_manager.get_prompt_by_name(name)
    if prompt:
        content = prompt["content"]
        if len(content) > 1000:
            content = content[:1000] + "..."

        embed = discord.Embed(
            title=f"📋 Preview: {prompt['name']}", 
            description=f"```{content}```",
            color=0x0099ff
        )
        embed.add_field(name="Created by", value=f"<@{prompt['created_by']}>", inline=True)
        embed.add_field(name="Usage count", value=str(prompt['usage_count']), inline=True)

        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"❌ - prompt '{name}' not found.")

@bot.tree.command(name="prompt_delete", description="Delete a system prompt")
@app_commands.describe(name="Name of the prompt to delete")
@app_commands.autocomplete(name=prompt_name_autocomplete)
async def delete_prompt(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    try:
        success = prompt_manager.delete_prompt(name, str(interaction.user.id))
        if success:
            await interaction.followup.send(f"✅ Deleted prompt: **{name}**")
        else:
            await interaction.followup.send(f"❌ Prompt '{name}' not found")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}")

@bot.command()
async def dox(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author

    attrs = await DiscordService.get_attr_dict(member)
    if hasattr(member, "_user"):
        user_attrs = await DiscordService.get_attr_dict(member._user)
    else:
        user_attrs = {}

    out = []
    out.append("Member attributes:")
    for k, v in attrs.items():
        out.append(f"{k}: {v}")

    if user_attrs:
        out.append("\nUser attributes:")
        for k, v in user_attrs.items():
            out.append(f"{k}: {v}")

    text = "\n".join(out)

    msg_limit = 1900
    chunks = [text[i:i+msg_limit] for i in range(0, len(text), msg_limit)]

    for chunk in chunks:
        await ctx.send(f"```{chunk}```")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    message_history = []

    if message.channel.id == channel_id or bot.user.mentioned_in(message) or (message.reference and message.reference.resolved and message.reference.resolved.author == bot.user):
        async with message.channel.typing():
            async for msg_in_history in message.channel.history(limit=max_history):
                if msg_in_history.id == message.id:
                    continue
                message_history.append(f'{msg_in_history.author.display_name}:  {msg_in_history.content}')

            message_history.reverse()  
            mention_pattern = rf'<@!?\s*{bot.user.id}>'
            prompt = re.sub(mention_pattern, '', message.content).strip()
            
            attachment_url = await GeminiService.check_for_attachment(message)

            if attachment_url:
                image_data = await GeminiService.download_image(attachment_url)

                if not image_data:
                    await message.channel.send('Unable to download the image.')
                    return

                try:
                    image_data.seek(0)
                    pil_image = Image.open(image_data)

                    if pil_image.mode in ('P', 'RGBA', 'LA', 'I'):
                        pil_image = pil_image.convert('RGB')
                    
                    response = await GeminiService.generate_text_response_using_image(pil_image, prompt, message_history)
                    await DiscordService.send_response(message, response)

                except Exception as e:
                    print(f"error processing image: {e}")
                    await message.channel.send("error processing the image.")
                return

            else:
                response = await GeminiService.generate_text_response(prompt, message_history)

                await DiscordService.send_response(message, response)

    await bot.process_commands(message)

if __name__ == "__main__":
    prompt_manager = PromptManager("prompts.json")

    async def main():
        async with bot:
            await bot.load_extension("command_manager")
            await bot.start(DISCORD_TOKEN)

    asyncio.run(main())
