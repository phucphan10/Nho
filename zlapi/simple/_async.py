# -*- coding: UTF-8 -*-

import os
import json
import time
import hashlib
import functools
import asyncio, threading

from ..Async import _state
from .. import _util
from ..models import *
from concurrent.futures import ThreadPoolExecutor
		
pool = ThreadPoolExecutor()
		

class ZaloAPI(object):
	def __init__(self, phone, password, imei, session_cookies=None, user_agent=None, auto_login=True, prefix=""):
		"""Initialize and log in the client.
		
		Args:
			imei (str): The device imei is logged into Zalo
			phone (str): Zalo account phone number
			password (str): Zalo account password
			auto_login (bool): Automatically log in when initializing ZaloAPI (Default: True)
			user_agent (str): Custom user agent to use when sending requests. If `None`, user agent will be chosen from a premade list
			session_cookies (dict): Cookies from a previous session (Required if logging in with cookies)
			
		Raises:
			ZaloLoginError: On failed login
			LoginMethodNotSupport: If method login not support
		"""
		self.prefix = prefix
		self.register_commands = {}
		self.register_messages = []
		
		self._state = _state.State()
		self._condition = threading.Event()
		self._listening = False
		
		if auto_login:
			if (
				not session_cookies 
				or not self.set_session(session_cookies) 
				or not self.is_logged_in()
			):
				asyncio.run(self.login(phone, password, imei, user_agent))
	
	def uid(self):
		"""The ID of the client."""
		return self.uid
	
	"""
	REGISTER COMMANDS EVENTS
	"""
	
	@staticmethod
	def check_commands_input(commands, method_name):
		if not isinstance(commands, list) or not all(isinstance(item, str) for item in commands):
			print(f"{method_name}: Commands filter should be list of strings (commands), unknown type supplied to the 'commands' filter list. Not able to use the supplied type.")
	
	
	@staticmethod
	def add_register_handler(func):
		@functools.wraps(func)
		async def wrapper(self, ctx):
			await func(self, ctx)
			if str(ctx.message) in self.register_commands:
				await self.register_commands[ctx.message](ctx)
			
			for funcheck, condition in self.register_messages:
				if condition(str(ctx.message)):
					await funcheck(ctx)
			
		return wrapper
	
	
	def register_handler(self, message=None, commands=None):
		def decorator(func):
			if commands is not None:
				self.check_commands_input(commands, "register_handler")
				
				if isinstance(commands, str):
					self.register_commands[self.prefix + commands] = func
				else:
					self.register_commands = {self.prefix + command: func for command in commands}
			
			if message:
				self.register_messages.append((func, message))
			
			return func
		
		return decorator
	
	def events(self, func):
		setattr(self, func.__name__, func)
	
	"""
	END REGISTER COMMANDS EVENTS
	"""
	
	"""
	INTERNAL REQUEST METHODS
	"""
	
	async def _get(self, *args, **kwargs):
		return await self._state._get(*args, **kwargs)
		
	async def _post(self, *args, **kwargs):
		return await self._state._post(*args, **kwargs)
	
	"""
	END INTERNAL REQUEST METHODS
	"""
	
	"""
	EXTENSIONS METHODS
	"""
	
	def _encode(self, params):
		return _util.zalo_encode(params, self._state._config.get("secret_key"))
		
	def _decode(self, params):
		return _util.zalo_decode(params, self._state._config.get("secret_key")) 
		
	"""
	END EXTENSIONS METHODS
	"""
	
	"""
	LOGIN METHODS
	"""
	
	def is_logged_in(self):
		"""Get data from config to check the login status.

		Returns:
			bool: True if the client is still logged in
		"""
		return self._state.is_logged_in()
		
	async def get_session(self):
		"""Retrieve session cookies.
			
		Returns:
			dict: A dictionary containing session cookies
		"""
		return await self._state.get_cookies()
		
	def set_session(self, session_cookies):
		"""Load session cookies.
		
		Warning:
			Error sending requests if session cookie is wrong
			
		Args:
			session_cookies (dict): A dictionary containing session cookies
			
		Returns:
			Bool: False if ``session_cookies`` does not contain proper cookies
		"""
		try:
			if not isinstance(session_cookies, dict):
				return False
			# Load cookies into current session
			self._state.set_cookies(session_cookies)
			self.uid = self._state.user_id
		except Exception as e:
			print("Failed loading session")
			return False
		return True
	
	async def get_secret_key(self):
		"""Retrieve secret key to encode/decode payload.
			
		Returns:
			str: A secret key string with base64 encode
		"""
		return await self._state.get_secret_key()
		
	def set_secret_key(self, secret_key):
		"""Load secret key.
		
		Warning:
			Error (enc/de)code payload if secret key is wrong
			
		Args:
			secret_key (str): A secret key string with base64 encode
			
		Returns:
			bool: False if ``secret_key`` not correct to (en/de)code the payload
		"""
		try:
			self._state.set_secret_key(secret_key)
			
			return True
		except:
			return False
	
	async def login(self, phone, password, imei, user_agent=None):
		"""Login the user, using ``phone`` and ``password``.
			
		If the user is already logged in, this will do a re-login.
				
		Args:
			imei (str): The device imei is logged into Zalo
			phone (str): Zalo account phone number
			password (str): Zalo account password
			user_agent (str): Custom user agent to use when sending requests. If `None`, user agent will be chosen from a premade list
			
		Raises:
			ZaloLoginError: On failed login
			LoginMethodNotSupport: If method login not support
		"""
		if not (phone and password):
			raise ZaloUserError("Phone and password not set")
		
		await self.on_logging_in()
		
		await self._state.login(
			phone,
			password,
			imei,
			user_agent=user_agent
		)
		try:
			self._imei = self._state.user_imei
			self.uid = (await self.fetch_account_info()).profile.get("userId", self._state.user_id)
		except:
			self._imei = None
			self.uid = self._state.user_id
		
		await self.on_logged_in(self._state._config.get("phone_number"))
		
	"""
	END LOGIN METHODS
	"""
	
	"""
	ATTACHMENTS METHODS
	"""
	
	async def _uploadImage(self, filePath, thread_id, thread_type):
		"""Upload images to Zalo.
			
		Args:
			filePath (str): Image url to send
			thread_id (int | str): User/Group ID to send to.
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			dict: A dictionary containing the image info just uploaded
			dict: A dictionary containing error_code, response if failed
			
		Raises:
			ZaloAPIException: If request failed
		"""
		if not os.path.exists(filePath):
			raise ZaloUserError(f"{filePath} not found")
			
		files = [("chunkContent", open(filePath, "rb"))]
		fileSize = len(open(filePath, "rb").read())
		fileName = filePath if "/" not in filePath else filePath.rstrip("/")[1]
		
		params = {
			"params": {
				"totalChunk": 1,
				"fileName": fileName,
				"clientId": _util.now(),
				"totalSize": fileSize,
				"imei": self._imei,
				"isE2EE": 0,
				"jxl": 0,
				"chunkId": 1
			},
			"zpw_ver": 635,
			"zpw_type": 30,
		}
		
		if thread_type == ThreadType.USER:
			url = "https://tt-files-wpa.chat.zalo.me/api/message/photo_original/upload"
			params["type"] = 2
			params["params"]["toid"] = str(thread_id)
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-files-wpa.chat.zalo.me/api/group/photo_original/upload"
			params["type"] = 11
			params["params"]["grid"] = str(thread_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		params["params"] = self._encode(params["params"])
		
		data = await self._post(url, params=params, data=files)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(data["data"])
			results = results.get("data") if results.get("error_code") == 0 else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return results
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
		
	"""
	END ATTACHMENTS METHODS
	"""
	
	"""
	FETCH METHODS
	"""
	
	async def fetch_account_info(self):
		"""fetch account information of the client 
		
		Returns:
			object: `User` client info
			dict: A dictionary containing error_code, response if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"params": self._encode({
				"avatar_size": 120,
				"imei": self._imei
			}),
			"zpw_ver": 635,
			"zpw_type": 30,
			"os": 8,
			"browser": 0
		}
		
		data = await self._get("https://tt-profile-wpa.chat.zalo.me/api/social/profile/me-v2", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("error_code") == 0 else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def fetch_phone_number(self, phoneNumber, language="vi"):
		"""Fetch user info by Phone Number.
		
		Not available with hidden phone numbers
		
		Args:
			phoneNumber (int | str): Phone number to fetch information
			language (str): Language for response (not sure | Default: vi)
		
		Returns:
			object: `User` user(s) info
			dict: A dictionary containing error_code, response if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		
		phone = "84" + str(phoneNumber) if str(phoneNumber)[:1] != "0" else "84" + str(phoneNumber)[1:]
		
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"params": self._encode({
				"phone": phone,
				"avatar_size": 240,
				"language": language,
				"imei": self._imei,
				"reqSrc": 85
			})
		}
		
		data = await self._get("https://tt-friend-wpa.chat.zalo.me/api/friend/profile/get", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
		
	async def fetch_user_info(self, userId):
		"""Fetch user info by ID.
		
		Args:
			userId (int | str | list): User(s) ID to get info
		
		Returns:
			object: `User` user(s) info
			dict: A dictionary containing error_code, response if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": {
				"phonebook_version": int(_util.now() / 1000),
				"friend_pversion_map": [],
				"avatar_size": 120,
				"language": "vi",
				"show_online_status": 1,
				"imei": self._imei
			}
		}
		
		if isinstance(userId, list):
			for i in range(len(userId)):
				userId[i] = str(userId[i]) + "_0"
			payload["params"]["friend_pversion_map"] = userId
			
		else:
			payload["params"]["friend_pversion_map"].append(str(userId) + "_0")
			
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post("https://tt-profile-wpa.chat.zalo.me/api/social/friend/getprofiles/v2", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("error_code") == 0 else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def fetch_group_info(self, groupId):
		"""Fetch group info by ID.
		
		Args:
			groupId (int | str | dict): Group(s) ID to get info
		
		Returns:
			object: `Group` group info
			dict: A dictionary containing error_code, response if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": {
				"gridVerMap": {}
			}
		}
		
		if isinstance(groupId, dict):
			for i in groupId:
				payload["params"]["gridVerMap"][str(i)] = 0
		else:
			payload["params"]["gridVerMap"][str(groupId)] = 0
			
		payload["params"]["gridVerMap"] = json.dumps(payload["params"]["gridVerMap"])
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post("https://tt-group-wpa.chat.zalo.me/api/group/getmg-v2", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("error_code") == 0 else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
		
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def fetch_all_friends(self):
		"""Fetch all users the client is currently chatting with (only friends).
		
		Returns:
			object: `User` all friend IDs
			any: If response is not list friends
			
		Raises:
			ZaloAPIException: If request failed
		"""
		
		params = {
			"params": self._encode({
				"incInvalid": 0,
				"page": 1,
				"count": 20000,
				"avatar_size": 120,
				"actiontime": 0
			}),
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		data = await self._get("https://profile-wpa.chat.zalo.me/api/social/friend/getfriends", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			datas = []
			if results.get("data"):
				for data in results.get("data"):
					datas.append(User(**data))
			
			return datas
					
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
		
	async def fetch_all_groups(self):
		"""Fetch all group IDs are joining and chatting.
		
		Returns:
			object: `Group` all group IDs
			any: If response is not all group IDs
		
		Raises:
			ZaloAPIException: If request failed
		"""
		
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://tt-group-wpa.chat.zalo.me/api/group/getlg/v4", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("error_code") == 0 else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
		
	"""
	END FETCH METHODS
	"""
	
	"""
	GET METHODS
	"""
	
	async def get_last_msgs(self):
		"""Get last message the client's friends/group chat room.
			
		Returns:
			object: `User` last msg data
			dict: A dictionary containing error_code, response if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": "635",
			"zpw_type": "30",
			"params": self._encode({
				"threadIdLocalMsgId": json.dumps({}),
				"imei": self._imei
			})
		}
		
		data = await self._get("https://tt-convers-wpa.chat.zalo.me/api/preloadconvers/get-last-msgs", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("error_code") == 0 else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def get_recent_group(self, groupId):
		"""Get recent messages in group by ID.
			
		Args:
			groupId (int | str): Group ID to get recent msgs
			
		Returns:
			object: `Group` List msg data in groupMsgs
			dict: A dictionary containing error_code, response if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"params": self._encode({
				"groupId": str(groupId),
				"globalMsgId": 10000000000000000,
				"count": 50,
				"msgIds": [],
				"imei": self._imei,
				"src": 1
			}),
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0,
		}
		
		data = await self._get("https://tt-group-cm.chat.zalo.me/api/cm/getrecentv2", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = json.loads(results.get("data")) if results.get("error_code") == 0 else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def _getGroupBoardList(self, board_type, page, count, last_id, last_type, groupId):
		params = {
			"params": self._encode({
				"group_id": str(groupId),
				"board_type": board_type,
				"page": page,
				"count": count,
				"last_id": last_id,
				"last_type": last_type,
				"imei": self._imei
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://groupboard-wpa.chat.zalo.me/api/board/list", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = json.loads(results.get("data")) if results.get("error_code") == 0 else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			results = Group.fromDict(results, None) if results.get("error_code") == 0 else results
			
			return results
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def get_group_board_list(self, groupId, page=1, count=20, last_id=0, last_type=0):
		"""Get group board list (pinmsg, note, poll) by ID.
			
		Args:
			groupId (int | str): Group ID to get board list
			page (int): Number of pages to retrieve data from
			count (int): Amount of data to retrieve per page (5 poll, ..)
			last_id (int): Default (no description)
			last_type (int): Default (no description)
			
		Returns:
			object: `Group` board data in group
			dict: A dictionary containing error_code, response if failed
			
		Raises:
			ZaloAPIException: If request failed
		"""
		response = await self._getGroupBoardList(0, page, count, last_id, last_type, groupId)
		
		return response
	
	async def get_group_pinmsg(self, groupId, page=1, count=20, last_id=0, last_type=0):
		"""Get group pinned messages by ID.
			
		Args:
			groupId (int | str): Group ID to get pinned messages
			page (int): Number of pages to retrieve data from
			count (int): Amount of data to retrieve per page (5 message, ..)
			last_id (int): Default (no description)
			last_type (int): Default (no description)
			
		Returns:
			object: `Group` pinned messages in group
			dict: A dictionary containing error_code, response if failed
			
		Raises:
			ZaloAPIException: If request failed
		"""
		response = await self._getGroupBoardList(2, page, count, last_id, last_type, groupId)
		
		return response
	
	async def get_group_note(self, groupId, page=1, count=20, last_id=0, last_type=0):
		"""Get group notes by ID.
			
		Args:
			groupId (int | str): Group ID to get notes
			page (int): Number of pages to retrieve data from
			count (int): Amount of data to retrieve per page (5 notes, ..)
			last_id (int): Default (no description)
			last_type (int): Default (no description)
			
		Returns:
			object: `Group` notes in group
			dict: A dictionary containing error_code, response if failed
			
		Raises:
			ZaloAPIException: If request failed
		"""
		response = await self._getGroupBoardList(1, page, count, last_id, last_type, groupId)
		
		return response
	
	async def get_group_poll(self, groupId, page=1, count=20, last_id=0, last_type=0):
		"""Get group polls by ID.
			
		Args:
			groupId (int | str): Group ID to get polls
			page (int): Number of pages to retrieve data from
			count (int): Amount of data to retrieve per page (5 poll, ..)
			last_id (int): Default (no description)
			last_type (int): Default (no description)
			
		Returns:
			object: `Group` polls in group
			dict: A dictionary containing error_code, response if failed
			
		Raises:
			ZaloAPIException: If request failed
		"""
		response = await self._getGroupBoardList(3, page, count, last_id, last_type, groupId)
		
		return response
	
	"""
	END GET METHODS
	"""
	
	"""
	ACCOUNT ACTION METHODS
	"""
	
	async def change_account_setting(self, name, dob, gender, biz={}, language="vi"):
		"""Change account information.
		
		Args:
			name (str): The new account name
			dob (str): Date of birth wants to change (format: year-month-day)
			gender (int | str): Gender wants to change (0 = Male, 1 = Female)
			biz (unknown): idk this
			language (str): Zalo language wants to change (default = vn)
		
		Returns:
			object: `User` change account setting status
			dict: A dictionary containing error_code, response if failed
			
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"profile": json.dumps({
					"name": name,
					"dob": dob,
					"gender": int(gender)
				}),
				"biz": json.dumps(biz),
				"language": language
			})
		}
		
		data = await self._post("https://tt-profile-wpa.chat.zalo.me/api/social/profile/update", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def change_account_avatar(self, filePath, width=500, height=500, language="vn", size=None):
		"""Upload/Change account avatar.
		
		Args:
			filePath (str): A path to the image to upload/change avatar
			size (int): Avatar image size (default = auto)
			width (int): Width of avatar image
			height (int): height of avatar image
			language (int | str): Zalo Website language ? (idk)
		
		Returns:
			object: `User` Account avatar change status
			None: If requet success/failed depending on the case
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		if not os.path.exists(filePath):
			raise ZaloUserError(f"{filePath} not found")
		
		size = os.stat(filePath).st_size if not size else size
		files = [("fileContent", open(filePath, "rb"))]
		
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"params": self._encode({
				"avatarSize": 120,
				"clientId": str(self.uid) + _util.formatTime("%H:%M %d/%m/%Y"),
				"language": language,
				"metaData": json.dumps({
					"origin": {
						"width": width,
						"height": height
					},
					"processed": {
						"width": width,
						"height": height,
						"size": size
					}
				})
			})
		}
		
		data = await self._post("https://tt-files-wpa.chat.zalo.me/api/profile/upavatar", params=params, data=files)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	"""
	END ACCOUNT ACTION METHODS
	"""
	
	"""
	USER ACTION METHODS
	"""
	
	async def send_friend_request(self, userId, msg, language="vi"):
		"""Send friend request to a user by ID.
			
		Args:
			userId (int | str): User ID to send friend request
			msg (str): Friend request message
			language (str): Response language or Zalo interface language

		Returns:
			object: `User` Friend requet response
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"toid": str(userId),
				"msg": msg,
				"reqsrc": 30,
				"imei": self._imei,
				"language": language,
				"srcParams": json.dumps({
					"uidTo": str(userId)
				})
			})
		}
		
		data = await self._post("https://tt-friend-wpa.chat.zalo.me/api/friend/sendreq", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def block_view_feed(self, userId, isBlockFeed):
		"""Block/Unblock friend view feed by ID.
			
		Args:
			userId (int | str): User ID to block/unblock view feed
			isBlockFeed (int): Block/Unblock friend view feed (1 = True | 0 = False)
		
		Returns:
			object: `User` Friend requet response
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"fid": str(userId),
				"isBlockFeed": isBlockFeed,
				"imei": self._imei
			})
		}
		
		data = await self._post("https://tt-friend-wpa.chat.zalo.me/api/friend/feed/block", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def block_user(self, userId):
		"""Block user by ID.
			
		Args:
			userId (int | str): User ID to block
		
		Returns:
			object: `User` Block response
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"fid": str(userId),
				"imei": self._imei
			})
		}
		
		data = await self._post("https://tt-friend-wpa.chat.zalo.me/api/friend/block", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def unblock_user(self, userId):
		"""Unblock user by ID.
			
		Args:
			userId (int | str): User ID to unblock
		
		Returns:
			object: `User` Unblock response
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"fid": str(userId),
				"imei": self._imei
			})
		}
		
		data = await self._post("https://tt-friend-wpa.chat.zalo.me/api/friend/unblock", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return User.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	"""
	END USER ACTION METHODS
	"""
	
	"""
	GROUP ACTION METHODS
	"""
	
	async def create_group(self, name=None, description=None, members=[], nameChanged=1, createLink=1):
		"""Create a new group.
			
		Args:
			name (str): The new group name
			description (str): Description of the new group
			members (str | list): List/String member IDs add to new group
			nameChanged (int - auto): Will use default name if disabled (0), else (1)
			createLink (int - default): Create a group link? Default = 1 (True)
			
		Returns:
			object: `Group` new group response
			dict: A dictionary containing error_code, response if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		memberTypes = []
		nameChanged = 1 if name else 0
		name = name or "Default Group Name"
		
		if members and isinstance(members, list):
			members = [str(member) for member in members]
		else:
			members = [str(members)]
			
		if members:
			for i in members:
				memberTypes.append(-1)
			
		params = {
			"params": self._encode({
				"clientId": _util.now(),
				"gname": name,
				"gdesc": description,
				"members": members,
				"memberTypes": memberTypes,
				"nameChanged": nameChanged,
				"createLink": createLink,
				"clientLang": "vi",
				"imei": self._imei,
				"zsource": 601
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://tt-group-wpa.chat.zalo.me/api/group/create/v2", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return results
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def change_group_avatar(self, filePath, groupId):
		"""Upload/Change group avatar by ID.
		
		Client must be the Owner of the group
		(If the group does not allow members to upload/change)
			
		Args:
			filePath (str): A path to the image to upload/change avatar
			groupId (int | str): Group ID to upload/change avatar
			
		Returns:
			object: `Group` Group avatar change status
			None: If requet success/failed depending on the case
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		if not os.path.exists(filePath):
			raise ZaloUserError(f"{filePath} not found")
			
			
		files = [("fileContent", open(filePath, "rb"))]
		
		params = {
			"params": self._encode({
				"grid": str(groupId),
				"avatarSize": 120,
				"clientId": "g" + str(groupId) + _util.formatTime("%H:%M %d/%m/%Y"),
				"originWidth": 640,
				"originHeight": 640,
				"imei": self._imei
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._post("https://tt-files-wpa.chat.zalo.me/api/group/upavatar", params=params, data=files)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def change_group_name(self, groupName, groupId):
		"""Set/Change group name by ID.
		
		Client must be the Owner of the group
		(If the group does not allow members to change group name)
			
		Args:
			groupName (str): Group name to change
			groupId (int | str): Group ID to change name
			
		Returns:
			object: `Group` Group name change status
			None: If requet success/failed depending on the case
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"gname": groupName,
				"grid": str(groupId)
			})
		}
		
		data = await self._post("https://tt-group-wpa.chat.zalo.me/api/group/updateinfo", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def changeGroupDesc(self, groupDesc, groupId):
		"""Not Available Yet"""
	
	async def change_group_setting(self, groupId, defaultMode="default", **kwargs):
		"""Update group settings by ID.
		
		Client must be the Owner/Admin of the group.
		
		Warning:
			Other settings will default value if not set. See `defaultMode`
		
		Args:
			groupId (int | str): Group ID to update settings
			defaultMode (str): Default mode of settings
			
				default: Group default settings
				anti-raid: Group default settings for anti-raid
			
			**kwargs: Group settings kwargs, Value: (1 = True, 0 = False)
			
				blockName: Không cho phép user đổi tên & ảnh đại diện nhóm
				signAdminMsg: Đánh dấu tin nhắn từ chủ/phó nhóm
				addMemberOnly: Chỉ thêm members (Khi tắt link tham gia nhóm)
				setTopicOnly: Cho phép members ghim (tin nhắn, ghi chú, bình chọn)
				enableMsgHistory: Cho phép new members đọc tin nhắn gần nhất
				lockCreatePost: Không cho phép members tạo ghi chú, nhắc hẹn
				lockCreatePoll: Không cho phép members tạo bình chọn
				joinAppr: Chế độ phê duyệt thành viên
				bannFeature: Default (No description)
				dirtyMedia: Default (No description)
				banDuration: Default (No description)
				lockSendMsg: Không cho phép members gửi tin nhắn
				lockViewMember: Không cho phép members xem thành viên nhóm
				blocked_members: Danh sách members bị chặn
		
		Returns:
			object: `Group` Group settings change status
			None: If requet success/failed depending on the case
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		if defaultMode == "anti-raid":
			defSetting = {
				"blockName": 1,
				"signAdminMsg": 1,
				"addMemberOnly": 0,
				"setTopicOnly": 1,
				"enableMsgHistory": 1,
				"lockCreatePost": 1,
				"lockCreatePoll": 1,
				"joinAppr": 1,
				"bannFeature": 0,
				"dirtyMedia": 0,
				"banDuration": 0,
				"lockSendMsg": 0,
				"lockViewMember": 0,
			}
		else:
			defSetting = self.fetchGroupInfo(groupId).gridInfoMap
			defSetting = defaultSettings[str(groupId)]["setting"]
			
		blockName = kwargs.get("blockName", defSetting.get("blockName", 1))
		signAdminMsg = kwargs.get("signAdminMsg", defSetting.get("signAdminMsg", 1))
		addMemberOnly = kwargs.get("addMemberOnly", defSetting.get("addMemberOnly", 0))
		setTopicOnly = kwargs.get("setTopicOnly", defSetting.get("setTopicOnly", 1))
		enableMsgHistory = kwargs.get("enableMsgHistory", defSetting.get("enableMsgHistory", 1))
		lockCreatePost = kwargs.get("lockCreatePost", defSetting.get("lockCreatePost", 1))
		lockCreatePoll = kwargs.get("lockCreatePoll", defSetting.get("lockCreatePoll", 1))
		joinAppr = kwargs.get("joinAppr", defSetting.get("joinAppr", 1))
		bannFeature = kwargs.get("bannFeature", defSetting.get("bannFeature", 0))
		dirtyMedia = kwargs.get("dirtyMedia", defSetting.get("dirtyMedia", 0))
		banDuration = kwargs.get("banDuration", defSetting.get("banDuration", 0))
		lockSendMsg = kwargs.get("lockSendMsg", defSetting.get("lockSendMsg", 0))
		lockViewMember = kwargs.get("lockViewMember", defSetting.get("lockViewMember", 0))
		blocked_members = kwargs.get("blocked_members", [])
		
		params = {
			"params": self._encode({
				"blockName": blockName,
				"signAdminMsg": signAdminMsg,
				"addMemberOnly": addMemberOnly,
				"setTopicOnly": setTopicOnly,
				"enableMsgHistory": enableMsgHistory,
				"lockCreatePost": lockCreatePost,
				"lockCreatePoll": lockCreatePoll,
				"joinAppr": joinAppr,
				"bannFeature": bannFeature,
				"dirtyMedia": dirtyMedia,
				"banDuration": banDuration,
				"lockSendMsg": lockSendMsg,
				"lockViewMember": lockViewMember,
				"blocked_members": blocked_members,
				"grid": str(groupId),
				"imei":self._imei
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://tt-group-wpa.chat.zalo.me/api/group/setting/update", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def change_group_owner(self, newAdminId, groupId):
		"""Change group owner (yellow key) by ID.
		
		Client must be the Owner of the group.
			
		Args:
			newAdminId (int | str): members ID to changer owner
			groupId (int | str): ID of the group to changer owner
			
		Returns:
			object: `Group` Group owner change status
			None: If requet success/failed depending on the case
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"params": self._encode({
				"grid": str(groupId),
				"newAdminId": str(newAdminId),
				"imei": self._imei,
				"language": "vi"
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://tt-group-wpa.chat.zalo.me/api/group/change-owner", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def add_users_to_group(self, user_ids, groupId):
		"""Add friends/users to a group.
			
		Args:
			user_ids (str | list): One or more friend/user IDs to add
			groupId (int | str): Group ID to add friend/user to
		
		Returns:
			object: `Group` add friend/user data
			dict: A dictionary containing error_code, response if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		memberTypes = []
		
		if members and isinstance(members, list):
			members = [str(friend) for friend in friend_ids]
		else:
			members = [str(friend_ids)]
			
		if members:
			for i in members:
				memberTypes.append(-1)
		
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"grid": str(groupId),
				"members": members,
				"memberTypes": memberTypes,
				"imei": self._imei,
				"clientLang": "vi"
			})
		}
		
		data = await self._post("https://tt-group-wpa.chat.zalo.me/api/group/invite/v2", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def kick_users_in_group(self, members, groupId):
		"""Kickout members in group by ID.
		
		Client must be the Owner of the group.
		
		Args:
			members (str | list): One or More member IDs to kickout
			groupId (int | str): Group ID to kick member from
			
		Returns:
			object: `Group` kick data
			dict: A dictionary/object containing error responses
			
		Raises:
			ZaloAPIException: If request failed
		"""
		if isinstance(members, list):
			members = [str(member) for member in members]
		else:
			members = [str(members)]
			
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"grid": str(groupId),
				"members": members
			})
		}
		
		data = await self._post("https://tt-group-wpa.chat.zalo.me/api/group/kickout", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def add_group_admins(self, members, groupId):
		"""Add admins to the group (white key).
		
		Client must be the Owner of the group.
			
		Args:
			members (str | list): One or More member IDs to add
			groupId (int | str): Group ID to add admins
			
		Returns:
			object: `Group` Group admins add status
			None: If requet success/failed depending on the case
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		if isinstance(members, list):
			members = [str(member) for member in members]
		else:
			members = [str(members)]
			
		params = {
			"params": self._encode({
				"grid": str(groupId),
				"members": members,
				"imei": self._imei
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://tt-group-wpa.chat.zalo.me/api/group/admins/add", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
		
	async def remove_group_admins(self, members, groupId):
		"""Remove admins in the group (white key) by ID.
		
		Client must be the Owner of the group.
			
		Args:
			members (str | list): One or More admin IDs to remove
			groupId (int | str): Group ID to remove admins
			
		Returns:
			object: `Group` Group admins remove status
			None: If requet success/failed depending on the case
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		if isinstance(members, list):
			members = [str(member) for member in members]
		else:
			members = [str(members)]
			
		params = {
			"params": self._encode({
				"grid": str(groupId),
				"members": members,
				"imei": self._imei
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://tt-group-wpa.chat.zalo.me/api/group/admins/remove", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def delete_group_msg(self, msgId, ownerId, clientMsgId, groupId):
		"""Delete message in group by ID.
		
		Args:
			groupId (int | str): Group ID to delete message
			msgId (int | str): Message ID to delete
			ownerId (int | str): Owner ID of the message to delete
			clientMsgId (int | str): Client message ID to delete message
		
		Returns:
			object: `Group` delete message status
			dict: A dictionary containing error_code & responses if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"grid": str(groupId),
				"cliMsgId": _util.now(),
				"msgs": [{
					"cliMsgId": str(clientMsgId),
					"globalMsgId": str(msgId),
					"ownerId": str(ownerId),
					"destId": str(groupId)
				}],
				"onlyMe": 0
			})
		}
		
		data = await self._post("https://tt-group-wpa.chat.zalo.me/api/group/deletemsg", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def view_group_pending(self, groupId):
		"""See list of people pending approval in group by ID.
		
		Args:
			groupId (int | str): Group ID to view pending members
			
		Returns:
			object: `Group` pending responses
			dict: A dictionary containing error_code & responses if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"params": self._encode({
				"grid": str(groupId),
				"imei": self._imei
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://tt-group-wpa.chat.zalo.me/api/group/pending-mems/list", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def handle_group_pending(self, members, groupId, isApprove=True):
		"""Approve/Deny pending users to the group from the group's approval.
		
		Client must be the Owner of the group.
		
		Args:
			members (str | list): One or More member IDs to handle
			groupId (int | str): ID of the group to handle pending members
			isApprove (bool): Approve/Reject pending members (True | False)
			
		Returns:
			object: `Group` handle pending responses
			dict: A dictionary/object containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		if isinstance(members, list):
			members = [str(member) for member in members]
		else:
			members = [str(members)]
		
		params = {
			"params": self._encode({
				"grid": str(groupId),
				"members": members,
				"isApprove": 1 if isApprove else 0
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://tt-group-wpa.chat.zalo.me/api/group/pending-mems/review", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
				
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def view_poll_detail(self, pollId):
		"""View poll data by ID.
		
		Args:
			pollId (int | str): Poll ID to view detail
			
		Returns:
			object: `Group` poll data
			dict: A dictionary containing error_code & response if failed
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"params": self._encode({
				"poll_id": int(pollId),
				"imei":self._imei
			}),
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		data = await self._get("https://tt-group-wpa.chat.zalo.me/api/poll/detail", params=params)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def create_poll(
		self,
		question,
		options,
		groupId,
		expiredTime=0,
		pinAct=False,
		multiChoices=True,
		allowAddNewOption=True,
		hideVotePreview=False,
		isAnonymous=False
	):
		"""Create poll in group by ID.
		
		Client must be the Owner of the group.
		
		Args:
			question (str): Question for poll
			options (str | list): List options for poll
			groupId (int | str): Group ID to create poll from
			expiredTime (int): Poll expiration time (0 = no expiration)
			pinAct (bool): Pin action (pin poll)
			multiChoices (bool): Allows multiple poll choices
			allowAddNewOption (bool): Allow members to add new options
			hideVotePreview (bool): Hide voting results when haven't voted
			isAnonymous (bool): Hide poll voters
			
		Returns:
			object: `Group` poll create data
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": {
				"group_id": str(groupId),
				"question": question,
				"options": [],
				"expired_time": expiredTime,
				"pinAct": pinAct,
				"allow_multi_choices": multiChoices,
				"allow_add_new_option": allowAddNewOption,
				"is_hide_vote_preview": hideVotePreview,
				"is_anonymous": isAnonymous,
				"poll_type": 0,
				"src": 1,
				"imei": self._imei
			}
		}
		
		if isinstance(options, list):
			payload["params"]["options"] = options
		else:
			payload["params"]["options"].append(str(options))
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post("https://tt-group-wpa.chat.zalo.me/api/poll/create", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def lock_poll(self, pollId):
		"""Lock/end poll in group by ID.
		
		Client must be the Owner of the group.
		
		Args:
			pollId (int | str): Poll ID to lock
			
		Returns:
			None: If requet success
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"poll_id": int(pollId),
				"imei": self._imei
			})
		}
		
		data = await self._post("https://tt-group-wpa.chat.zalo.me/api/poll/end", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def disperse_group(self, groupId):
		"""Disperse group by ID.
		
		Client must be the Owner of the group.
			
		Args:
			groupId (int | str): Group ID to disperse
			
		Returns:
			None: If requet success
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": self._encode({
				"grid": str(groupId),
				"imei": self._imei
			})
		}
		
		data = await self._post("https://tt-group-wpa.chat.zalo.me/api/group/disperse", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("error_code") == 0 else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
		
	"""
	END GROUP ACTION METHODS
	"""
	
	"""
	SEND METHODS
	"""
	
	async def send(self, message, thread_id, thread_type=ThreadType.USER, mark_message=None):
		"""Send message to a thread.
			
		Args:
			message (Message): Message to send
			thread_id (int | str): User/Group ID to send to
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			object: `User/Group` (Returns msg ID just sent)
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		thread_id = str(int(thread_id) or self.uid)
		if message.mention:
			return await self.send_mention_message(message, thread_id)
		else:
			return await self.send_message(message, thread_id, thread_type, mark_message)
	
	async def send_message(self, message, thread_id, thread_type, mark_message=None):
		"""Send message to a thread (user/group).
			
		Args:
			message (Message): Message to send
			mark_message (str): Send messages as `Urgent` or `Important` mark
			thread_id (int | str): User/Group ID to send to
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			object: `User/Group` (Returns msg ID just sent)
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		payload = {
			"params": {
				"message": message.text,
				"clientId": _util.now(),
				"imei": self._imei,
				"ttl": 0,
			}
		}
		
		if mark_message and mark_message.lower() in ["important", "urgent"]:
			markType = 1 if mark_message.lower() == "important" else 2
			payload["params"]["metaData"] = {"urgency": markType}
		
		if message.style:
			payload["params"]["textProperties"] = message.style
			
		if thread_type == ThreadType.USER:
			url = "https://tt-chat2-wpa.chat.zalo.me/api/message/sms"
			payload["params"]["toid"] = str(thread_id)
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-group-wpa.chat.zalo.me/api/group/sendmsg"
			payload["params"]["visibility"] = 0
			payload["params"]["grid"] = str(thread_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def reply_message(self, message, replyMsg, thread_id, thread_type):
		"""Reply message in group by ID.
			
		Args:
			message (Message): Message Object
			replyMsg (Message): Message Object to reply
			thread_id (int | str): User/Group ID to send to.
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			object: `User/Group` (Returns msg ID just sent)
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		payload = {
			"params": {
				"message": message.text,
				"clientId": _util.now(),
				"qmsgOwner": str(int(replyMsg.uidFrom) or self.uid),
				"qmsgId": replyMsg.msgId,
				"qmsgCliId": replyMsg.cliMsgId,
				"qmsgType": 1,
				"qmsg": replyMsg.content,
				"qmsgTs": replyMsg.ts,
				"qmsgAttach": json.dumps({"properties": {"color":0,"size":0,"type":0,"subType":0,"ext": {"shouldParseLinkOrContact":0}}}),
				"qmsgTTL": 0,
				"ttl": 0
			}
		}
		
		if message.style:
			payload["params"]["textProperties"] = message.style
			
		if message.mention:
			payload["params"]["mentionInfo"] = message.mention
		
		if thread_type == ThreadType.USER:
			url = "https://tt-chat2-wpa.chat.zalo.me/api/message/quote"
			payload["params"]["toid"] = str(thread_id)
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-group-wpa.chat.zalo.me/api/group/quote"
			payload["params"]["visibility"] = 0
			payload["params"]["grid"] = str(thread_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def send_mention_message(self, message, groupId):
		"""Send message to a group with mention by ID.
			
		Args:
			mention (str): Mention format data to send
			message (Message): Message to send
			groupId: Group ID to send to.
			
		Returns:
			object: `User/Group` (Returns msg ID just sent)
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		payload = {
			"params": {
				"grid": str(groupId),
				"message": message.text,
				"mentionInfo": message.mention,
				"clientId": _util.now(),
				"visibility": 0,
				"ttl": 0
			}
		}
		
		if message.style:
			payload["params"]["textProperties"] = message.style
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post("https://tt-group-wpa.chat.zalo.me/api/group/mention", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return Group.fromDict(results, None)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def undo_message(self, msgId, cliMsgId, thread_id, thread_type):
		"""Undo message from the client by ID.
			
		Args:
			msgId (int | str): Message ID to undo
			cliMsgId (int | str): Client Msg ID to undo
			thread_id (int | str): User/Group ID to undo message
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			object: `User/Group` undo message status
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		payload = {
			"params": {
				"msgId": str(msgId),
				"cliMsgIdUndo": str(cliMsgId),
				"clientId": _util.now()
			} 
		}
		
		if thread_type == ThreadType.USER:
			url = "https://tt-chat3-wpa.chat.zalo.me/api/message/undo"
			payload["params"]["toid"] = str(thread_id)
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-group-wpa.chat.zalo.me/api/group/undomsg"
			payload["params"]["grid"] = str(thread_id)
			payload["params"]["visibility"] = 0
			payload["params"]["imei"] = self._imei
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def send_reaction(self, msgId, clientMsgId, reactionIcon, thread_id, thread_type, reactionType=75, msgType=1):
		"""Reaction message by ID.
			
		Args:
			msgId (int | str): Message ID to reaction
			clientMsgId (int | str): Client message ID to defind reaction
			reactionIcon (str): Icon/Text to reaction
			thread_id (int | str): Group/User ID contain message to reaction
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			object: `User/Group` message reaction data
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": {
				"react_list": [{
					"message": json.dumps({
						"rMsg": [{
							"gMsgID": int(msgId),
							"cMsgID": int(clientMsgId),
							"msgType": int(msgType)
						}],
						"rIcon": reactionIcon,
						"rType": reactionType,
						"source": 6
					}),
					"clientId": _util.now()
				}],
				"imei": self._imei
			}
		}
		
		if thread_type == ThreadType.USER:
			url = "https://reaction.chat.zalo.me/api/message/reaction"
			payload["params"]["toid"] = str(thread_id)
		elif thread_type == ThreadType.GROUP:
			url = "https://reaction.chat.zalo.me/api/group/reaction"
			payload["params"]["grid"] = str(thread_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def send_multi_reaction(self, reactionObj, reactionIcon, thread_id, thread_type, reactionType=75):
		"""Reaction message by ID.
			
		Args:
			reactionObj (MessageReaction): Message(s) data to reaction
			reactionIcon (str): Icon/Text to reaction
			thread_id (int | str): Group/User ID contain message to reaction
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			object: `User/Group` message reaction data
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": {
				"react_list": [{
					"message": {
						"rMsg": [],		
						"rIcon": reactionIcon,
						"rType": reactionType,
						"source": 6
					},
					"clientId": _util.now()
				}],
				"imei": self._imei
			}
		}
		
		if isinstance(reactionObj, dict):
			payload["params"]["react_list"][0]["message"]["rMsg"].append(reactionObj)
		elif isinstance(reactionObj, list):
			payload["params"]["react_list"][0]["message"]["rMsg"] = reactionObj
		else:
			raise ZaloUserError("Reaction type is invalid")
		
		if thread_type == ThreadType.USER:
			url = "https://reaction.chat.zalo.me/api/message/reaction"
			payload["params"]["toid"] = str(thread_id)
		elif thread_type == ThreadType.GROUP:
			url = "https://reaction.chat.zalo.me/api/group/reaction"
			payload["params"]["grid"] = str(thread_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"]["react_list"][0]["message"] = json.dumps(payload["params"]["react_list"][0]["message"])
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def send_remote_file(self, fileUrl, thread_id, thread_type, fileName="default", fileSize=None, extension="vrxx"):
		"""Send File to a User/Group with url.
			
		Args:
			fileUrl (str): File url to send
			fileName (str): File name to send
			fileSize (int): File size to send
			thread_id (int | str): User/Group ID to send to.
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			object: `User/Group` (Returns msg ID just sent)
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		try:
			async with aiohttp.ClientSession() as session:
				async with session.get(fileUrl) as response:
					if response.status_code == 200:
						fileSize = fileSize if fileSize else int(response.headers.get("Content-Length")) or len(response.content)
					else:
						fileSize = fileSize if fileSize else 0
					
					fileChecksum = hashlib.md5(response.content).hexdigest()
		
		except:
			raise ZaloAPIException("Unable to get url content")
		
		has_extension = fileName.rsplit(".")
		extension = has_extension[-1:][0] if len(has_extension) >= 2 else extension
		
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		payload = {
			"params": {
				"fileId": str(int(_util.now() * 2)),
				"checksum": fileChecksum,
				"checksumSha": "",
				"extension": extension,
				"totalSize": fileSize,
				"fileName": fileName,
				"clientId": _util.now(),
				"fType": 1,
				"fileCount": 0,
				"fdata": "{}",
				"fileUrl": fileUrl,
				"zsource": 401,
				"ttl": 0
			}
		}
		
		if thread_type == ThreadType.USER:
			url = "https://tt-files-wpa.chat.zalo.me/api/message/asyncfile/msg"
			payload["params"]["toid"] = str(thread_id)
			payload["params"]["imei"] = self._imei
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-files-wpa.chat.zalo.me/api/group/asyncfile/msg"
			payload["params"]["grid"] = str(thread_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def send_local_image(self, imagePath, thread_id, thread_type, width=2560, height=2560, message=None):
		"""Send Image to a User/Group with local file.
			
		Args:
			imagePath (str): Image directory to send
			imageWidth (int): Image width to send
			imageHeight (int): Image height to send
			message (Message): Message object to send
			thread_id (int | str): User/Group ID to send to.
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			object: `User/Group` objects
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		uploadImage = await self._uploadImage(imagePath, thread_id, thread_type)
		
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		payload = {
			"params": {
				"photoId": uploadImage["photoId"], # 318373455858
				"clientId": uploadImage["clientFileId"],
				"desc": message.text or "" if message else "",
				"width": width,
				"height": height,
				"rawUrl": uploadImage["normalUrl"],
				"thumbUrl": uploadImage["thumbUrl"],
				"hdUrl": uploadImage["hdUrl"],
				"thumbSize": "53932",
				"fileSize": "247671",
				"hdSize": "344622",
				"zsource": -1,
				"jcp": json.dumps({"sendSource": 1}),
				"ttl": 0,
				"imei": self._imei
			}
		}
		
		if message and message.mention:
			payload["params"]["mentionInfo"] = message.mention
			
		if thread_type == ThreadType.USER:
			url = "https://tt-files-wpa.chat.zalo.me/api/message/photo_original/send"
			payload["params"]["toid"] = str(thread_id)
			payload["params"]["normalUrl"] = uploadImage["normalUrl"]
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-files-wpa.chat.zalo.me/api/group/photo_original/send"
			payload["params"]["grid"] = str(thread_id)
			payload["params"]["oriUrl"] = uploadImage["normalUrl"]
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def send_sticker(self, stickerId, cateId, thread_id, thread_type):
		"""Send Sticker to a User/Group.
			
		Args:
			stickerId (int | str): Sticker id to send
			cateId (int | str): Sticker category id to send
			thread_id (int | str): User/Group ID to send to.
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			object: `User/Group` objects
			dict: A dictionary containing error responses
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		payload = {
			"params": {
				"stickerId": int(stickerId),
				"cateId": int(cateId),
				"type": 7,
				"clientId": _util.now(),
				"imei": self._imei,
				"ttl": 0,
			}
		}
		
		if thread_type == ThreadType.USER:
			url = "https://tt-chat2-wpa.chat.zalo.me/api/message/sticker"
			payload["params"]["zsource"] = 106
			payload["params"]["toid"] = str(thread_id)
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-group-wpa.chat.zalo.me/api/group/sticker"
			payload["params"]["zsource"] = 103
			payload["params"]["grid"] = str(thread_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
		
	async def send_custom_sticker(
		self,
		staticImgUrl,
		animationImgUrl,
		thread_id,
		thread_type,
		reply=None,
		width=None,
		height=None
	):
		"""Send custom (static/animation) sticker to a User/Group with url.
			
		Args:
			staticImgUrl (str): Image url (png, jpg, jpeg) format to create sticker
			animationImgUrl (str): Static/Animation image url (webp) format to create sticker
			thread_id (int | str): User/Group ID to send sticker to.
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			reply (int | str): Message ID to send stickers with quote
			width (int | str): Width of photo/sticker
			height (int | str): Height of photo/sticker
			
		Returns:
			object: `User/Group` sticker data
			dict: A dictionary containing error responses
			
		Raises:
			ZaloAPIException: If request failed
		"""
		width = int(width) if width else 498
		height = int(height) if height else 332
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		payload = {
			"params": {
				"clientId": _util.now(),
				"title": "",
				"oriUrl": staticImgUrl,
				"thumbUrl": staticImgUrl,
				"hdUrl": staticImgUrl,
				"width": width, #0
				"height": height, #0
				"properties": json.dumps({
					"subType": 0,
					"color": -1,
					"size": -1,
					"type": 3,
					"ext": json.dumps({
						"sSrcStr": "@STICKER",
						"sSrcType": 0
					})
				}),
				"contentId": _util.now(), #2842316716983420400
				"thumb_height": width,
				"thumb_width": height,
				"webp": json.dumps({
					"width": width, #0
					"height": height, #0
					"url": animationImgUrl
				}),
				"zsource": -1,
				"ttl": 0
			}
		}
		
		if reply:
			payload["params"]["refMessage"] = str(reply)
			
		if thread_type == ThreadType.USER:
			url = "https://tt-files-wpa.chat.zalo.me/api/message/photo_url"
			payload["params"]["toId"] = str(thread_id)
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-files-wpa.chat.zalo.me/api/group/photo_url"
			payload["params"]["visibility"] = 0
			payload["params"]["grid"] = str(thread_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def send_report(self, thread_id, thread_type, reason=0, content=None):
		"""Send report to Zalo.
		
		Args:
			reason (int): Reason for reporting
				1 = Nội dung nhạy cảm
				2 = Làm phiền
				3 = Lừa đảo
				0 = custom
			content (str): Report content (work if reason = custom)
			thread_id (int | str): User/Group ID to report
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
		
		Returns:
			object: `User/Group` send report response
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": {
				"uidTo": str(thread_id),
				"imei": self._imei
			}
		}
		
		payload["params"]["content"] = content if content and not reason else None if not content and not reason else ""
		payload["params"]["reason"] = random.randint(1, 3) if content == None else reason
		
		if thread_type == ThreadType.USER:
			payload["params"]["type"] = 2
		elif thread_type == ThreadType.GROUP:
			payload["params"]["type"] = 14
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post("https://tt-profile-wpa.chat.zalo.me/api/social/profile/reportabuse", params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			results = results.get("data") if results.get("data") else results
			if results == None:
				results = {"error_code": 1337, "error_message": "Data is None"}
			
			if isinstance(results, str):
				try:
					results = json.loads(results)
				except:
					results = {"error_code": 1337, "error_message": results}
			
			return (
				Group.fromDict(results, None) 
				if thread_type == ThreadType.GROUP else 
				User.fromDict(results, None)
			)
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	"""
	END SEND METHODS
	"""
	
	async def set_typing(self, thread_id, thread_type):
		"""Set users typing status.
			
		Args:
			thread_id (int | str): User/Group ID to change status in
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
		
		Raises:
			ZaloAPIException: If request failed
		"""
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": {
				"imei": self._imei
			}
		}
		
		if thread_type == ThreadType.USER:
			url = "https://tt-chat1-wpa.chat.zalo.me/api/message/typing"
			payload["params"]["toid"] = str(thread_id)
			payload["params"]["destType"] = 3
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-group-wpa.chat.zalo.me/api/group/typing"
			payload["params"]["grid"] = str(thread_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			results = self._decode(results)
			return True
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def mark_as_delivered(self, ctx):
		"""Mark a message as delivered.
		
		Args (Context):
			cliMsgId (int | str): Client message ID
			msgId (int | str): Message ID to set as delivered
			senderId (int | str): Message sender Id
			thread_id (int | str): User/Group ID to mark as delivered
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			bool: True
			
		Raises:
			ZaloAPIException: If request failed
		"""
		msgId = ctx.message_id
		method = ctx.message_object.msgType
		senderId = ctx.author_id
		cliMsgId = ctx.message_object.cliMsgId
		thread_id = ctx.thread_id
		thread_type = ctx.thread_type
		
		destination_id = "0" if thread_type == ThreadType.USER else thread_id
		
		params = {
			"zpw_ver": 635,
			"zpw_type": 30
		}
		
		payload = {
			"params": {
				"msgInfos": {
					"seen": 0,
					"data": [{
						"cmi": str(cliMsgId),
						"gmi": str(msgId),
						"si": str(senderId),
						"di": str(destination_id),
						"mt": method,
						"st": 3,
						"at": 0,
						"ts": str(_util.now())
					}]
				}
			}
		}
		
		if thread_type == ThreadType.USER:
			url = "https://tt-chat3-wpa.chat.zalo.me/api/message/deliveredv2"
			payload["params"]["msgInfos"]["data"][0]["cmd"] = 501
		else:
			url = "https://tt-group-wpa.chat.zalo.me/api/group/deliveredv2"
			payload["params"]["msgInfos"]["data"][0]["cmd"] = 521
			payload["params"]["msgInfos"]["grid"] = str(destination_id)
			payload["params"]["imei"] = self._imei
		
		payload["params"]["msgInfos"] = json.dumps(payload["params"]["msgInfos"])
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			context = ContextObject.fromDict({"msgId": msgId, "thread_id": thread_id, "thread_type": thread_type})
			await self.on_message_delivered(context)
			return True
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	async def mark_as_read(self, ctx):
		"""Mark a message as read.
		
		Args (Context):
			cliMsgId (int | str): Client message ID
			msgId (int | str): Message ID to set as delivered
			senderId (int | str): Message sender Id
			thread_id (int | str): User/Group ID to mark as read
			thread_type (ThreadType): ThreadType.USER, ThreadType.GROUP
			
		Returns:
			bool: True
			
		Raises:
			ZaloAPIException: If request failed
		"""
		msgId = ctx.message_id
		method = ctx.message_object.msgType
		senderId = ctx.author_id
		cliMsgId = ctx.message_object.cliMsgId
		thread_id = ctx.thread_id
		thread_type = ctx.thread_type
		
		destination_id = "0" if thread_type == ThreadType.USER else thread_id
		
		params = {
			"zpw_ver": 635,
			"zpw_type": 30,
			"nretry": 0
		}
		
		payload = {
			"params": {
				"msgInfos": {
					"data": [{
						"cmi": str(cliMsgId),
						"gmi": str(msgId),
						"si": str(senderId),
						"di": str(destination_id),
						"mt": method,
						"st": 3,
						"ts": str(_util.now())
					}]
				},
				"imei": self._imei
			}
		}
		
		if thread_type == ThreadType.USER:
			url = "https://tt-chat1-wpa.chat.zalo.me/api/message/seenv2"
			payload["params"]["msgInfos"]["data"][0]["at"] = 7
			payload["params"]["msgInfos"]["data"][0]["cmd"] = 501
			payload["params"]["senderId"] = str(destination_id)
		elif thread_type == ThreadType.GROUP:
			url = "https://tt-group-wpa.chat.zalo.me/api/group/seenv2"
			payload["params"]["msgInfos"]["data"][0]["at"] = 0
			payload["params"]["msgInfos"]["data"][0]["cmd"] = 511
			payload["params"]["grid"] = str(destination_id)
		else:
			raise ZaloUserError("Thread type is invalid")
		
		payload["params"]["msgInfos"] = json.dumps(payload["params"]["msgInfos"])
		payload["params"] = self._encode(payload["params"])
		
		data = await self._post(url, params=params, data=payload)
		results = data.get("data") if data.get("error_code") == 0 else None
		if results:
			context = ContextObject.fromDict({"msgId": msgId, "thread_id": thread_id, "thread_type": thread_type})
			await self.on_marked_seen(context)
			return True
			
		error_code = data.get("error_code")
		error_message = data.get("error_message") or data.get("data")
		raise ZaloAPIException(f"Error #{error_code} when sending requests: {error_message}")
	
	"""
	LISTEN METHODS
	"""
	
	async def _listen(self, delay=1):
		HasRead = set()
		while not self._condition.is_set():
			ListenTime = int((time.time() - 10) * 1000)
			
			if len(HasRead) > 10000000:
				HasRead.clear()
			
			messages = await self.get_last_msgs()
			groupmsg = messages.groupMsgs
			messages = messages.msgs
			
			loop = asyncio.get_event_loop()
			for message in messages + groupmsg:
				if int(message["ts"]) >= ListenTime and message["msgId"] not in HasRead:
					
					HasRead.add(message["msgId"])
					msgObj = MessageObject.fromDict(message, None)
					
					if message in messages:
						
						context = {"message_id": msgObj.msgId, "author_id": str(int(msgObj.uidFrom) or self.uid), "message": msgObj.content, "message_object": msgObj, "thread_id": str(int(msgObj.uidFrom) or msgObj.idTo), "thread_type": ThreadType.USER}
						context = ContextObject.fromDict(context)
						loop.create_task(self.onMessage(context))
					
					else:
						
						context = {"message_id": msgObj.msgId, "author_id": str(int(msgObj.uidFrom) or self.uid), "message": msgObj.content, "message_object": msgObj, "thread_id": str(int(msgObj.idTo) or msgObj.idTo), "thread_type": ThreadType.GROUP}
						context = ContextObject.fromDict(context)
						loop.create_task(self.onMessage(context))
			
			await asyncio.sleep(delay)
	
	
	async def _listen_test(self, delay=1):
		HasRead = set()
		Groups = [groupId for groupId in (await self.fetch_all_groups()).gridVerMap]
		while not self._condition.is_set():
			ListenTime = int((time.time() - 10) * 1000)
			
			if len(HasRead) > 10000000:
				HasRead.clear()
			
			messages = await self.get_last_msgs()
			messages = messages.msgs
			
			loop = asyncio.get_event_loop()
			for message in messages:
				if int(message["ts"]) >= ListenTime and message["msgId"] not in HasRead:
					
					HasRead.add(message["msgId"])
					msgObj = MessageObject.fromDict(message, None)
					context = {"message_id": msgObj.msgId, "author_id": str(int(msgObj.uidFrom) or self.uid), "message": msgObj.content, "message_object": msgObj, "thread_id": str(int(msgObj.uidFrom) or msgObj.idTo), "thread_type": ThreadType.USER}
					context = ContextObject.fromDict(context)
					loop.create_task(self.onMessage(context))
			
			
			for groupId in Groups:
				messages = await self.get_recent_group(groupId)
				
				try:
					messages = messages.groupMsgs
				except:
					messages = []
				
				for message in messages:
					if int(message["ts"]) >= ListenTime and message["msgId"] not in HasRead:
						
						HasRead.add(message["msgId"])
						msgObj = MessageObject.fromDict(message, None)
						context = {"message_id": msgObj.msgId, "author_id": int(msgObj.uidFrom) or self.uid, "message": msgObj.content, "message_object": msgObj, "thread_id": int(msgObj.idTo) or msgObj.idTo, "thread_type": ThreadType.GROUP}
						context = ContextObject.fromDict(context)
						loop.create_task(self.onMessage(context))
			
			await asyncio.sleep(delay)
	
	
	def startListening(self, delay=1, test=False, thread=False):
		"""Start listening from an external event loop.
		
		Args:
			delay (int): Delay time each time fetching a message
			test (bool): Listen `test` or `main` mode, Default: False (Main Mode)
			thread (bool): thread listening mode (Default: False)
		
		Raises:
			ZaloAPIException: If request failed
		"""
		self._condition.clear()
		if thread:
			loop = asyncio.get_event_loop()
			
			[
				pool.submit(loop.run_until_complete, self._listen(delay))
				if not test else
				pool.submit(loop.run_until_complete, self._listen_test(delay))
			]
			
			self._listening = True
		
		else:
			
			[
				asyncio.run(self._listen(delay))
				if not test else
				asyncio.run(self._listen_test(delay))
			]
	
	
	def stopListening(self):
		"""Stop the listening loop."""
		self._listening = False
		self._condition.set()
	
	
	def listen(self, delay=1, test=False, thread=False):
		"""Initialize and runs the listening loop continually.
		
		Args:
			delay (int): Delay time for each message fetch (Default: 1)
			test (bool): Listen test mode (Default: False)
			thread (bool): Listen in the thread (Default: False)
		
		"""
		asyncio.run(self.on_listening())
		self.startListening(delay, test, thread)
		if thread:
			while self._listening:
				pass
			
			self.stopListening()
	
	"""
	END LISTEN METHODS
	"""
	
	"""
	EVENTS
	"""
	
	async def on_logging_in(self, phone=None):
		"""Called when the client is logging in.
			
		Args:
			phone: The phone number of the client
		"""
		print("Logging in {}...".format(phone))
	
	
	async def on_logged_in(self, phone=None):
		"""Called when the client is successfully logged in.
			
		Args:
			phone: The phone number of the client
		"""
		print("Login of {} successful.".format(phone))
	
	
	async def on_listening(self):
		"""Called when the client is listening."""
		print("Listening...")
	
	
	async def on_message_delivered(self, ctx):
		"""Called when the client is listening, and the client has successfully marked messages as delivered.
		
		Args (Context):
			msg_ids: The messages that are marked as delivered
			thread_id: Thread ID that the action was sent to
			thread_type (ThreadType): Type of thread that the action was sent to
			ts: A timestamp of the action
		"""
		print(
			"Marked messages {} as delivered in [({}, {})] at {}.".format(
				ctx.msg_ids, ctx.thread_id, ctx.thread_type.name, int(_util.now() / 1000)
			)
		)
	
	
	async def on_marked_seen(self, ctx):
		"""Called when the client is listening, and the client has successfully marked messages as read/seen.
		
		Args (Context):
			msg_ids: The messages that are marked as read/seen
			thread_id: Thread ID that the action was sent to
			thread_type (ThreadType): Type of thread that the action was sent to
		"""
		print(
			"Marked messages {} as seen in [({}, {})] at {}.".format(
				ctx.msg_ids, ctx.thread_id, ctx.thread_type.name, int(_util.now() / 1000)
			)
		)
	
	
	async def on_message(self, ctx):
		"""Called when the client is listening, and somebody sends a message.

		Args:
			mid: The message ID
			author_id: The ID of the author
			message: The message content of the author
			message_object: The message (As a `Message` object)
			thread_id: Thread ID that the message was sent to.
			thread_type (ThreadType): Type of thread that the message was sent to.
		"""
		print("{} from {} in {}".format(ctx.message, ctx.thread_id, ctx.thread_type.name))
	
	
	@add_register_handler
	async def onMessage(self, ctx):
		await self.on_message(ctx)
		
	"""
	END EVENTS
	"""