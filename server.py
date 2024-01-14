import os
import select
import socket
import sys
import threading
import os
import json
import logging

from enum import IntEnum
from datetime import datetime

RECV_BUFFER = 1024

LOGGER = logging.getLogger(__name__)

logging.basicConfig(
	level=logging.NOTSET,
	format="%(asctime)s - %(levelname)s - %(message)s",
	handlers=[
		logging.StreamHandler(),
		logging.FileHandler("server.log")
	]
)

def formattedString(string):
	return f'{datetime.now().strftime("[%H:%M:%S]")} {string}'

#Enum class same as client.py to simplify usage
class msgTypes(IntEnum):
	QUIT = 0
	GCAST_MSG = 1
	UCAST_MSG= 2
	LOGIN_MSG = 3
	USER_REQ_MSG = 4
	SERVER_LS = 5
	DOWNLOAD_MSG = 6
	HEADER_DOWNLOAD_ERR = 7
	HEADER_DOWNLOAD_START = 8


	def __str__(self):
		return self.name

class InvalidMessageException(Exception):
	def __init__(self,message="An invalid message was passed to the download thread"):
		self.message = message
		super().__init__(self.message)

class DownloadThread(threading.Thread):
	def __init__(self,socket,downloadDir,daemon):
		super(DownloadThread,self).__init__(daemon=daemon)
		self.downloadSock = socket
		self.downloadDir = downloadDir
	
	def run(self):
		self.downloadMain()
	
	def downloadMain(self):
		try:
			#server receives a message specifying the filename requested associated with the message type DOWNLOAD_MSG
			data = self.downloadSock.recv(RECV_BUFFER)
			request = json.loads(data.decode('utf-8'))
			if request['msgType'] != msgTypes.DOWNLOAD_MSG:
				raise InvalidMessageException("Invalid download message")
			else:
				fileToGet = request['filename']
				if not os.path.exists(self.downloadDir+fileToGet):
					raise FileNotFoundError
				headerStartMessage = json.dumps({'msgType':msgTypes.HEADER_DOWNLOAD_START})
				self.downloadSock.send(headerStartMessage.encode('utf-8'))
				with open(self.downloadDir+fileToGet, "rb") as file:
					while True:
						data = file.read(RECV_BUFFER)
						if not data:
							break
						self.downloadSock.sendall(data)

		except FileNotFoundError:
			LOGGER.warning(f"An attempt was made to get a file that is not on the server")
			retMsg = {"msgType":msgTypes.HEADER_DOWNLOAD_ERR,"message":"File not found on the server"}
			retMsg = json.dumps(retMsg)
			self.downloadSock.send(retMsg.encode('utf-8'))
		except InvalidMessageException:
			LOGGER.warning("An invalid message was sent to the download socket")
			retMsg = {"msgType":msgTypes.HEADER_DOWNLOAD_ERR,"message":"Invalid message sent to download socket"}
			retMsg = json.dumps(retMsg)
			self.downloadSock.send(retMsg.encode('utf-8'))
		except Exception as e:
			LOGGER.error(e)
			retMsg = {"msgType":msgTypes.HEADER_DOWNLOAD_ERR,"message":f"Error on the server {str(e)}"}
			retMsg = json.dumps(retMsg)
			self.downloadSock.send(retMsg.encode('utf-8'))

		finally:
			self.downloadSock.close()
			return

class Server():
	def __init__(self,port):
		self.port = port
		self.connectionDict = dict()
		self.serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.downloadSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		
		self.serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.downloadSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

		self.downloadDir = "./ServerDownloads/"
	
	def serverMain(self):
		
		self.serverSocket.bind(("127.0.0.1",self.port))
		self.serverSocket.listen(0)
		self.downloadSocket.bind(("127.0.0.1",self.port + 1))
		self.downloadSocket.listen(0)

		LOGGER.info(f"New instance of server started on port {str(self.port)}")

		#Structure for self.connectionDict: socket:username. A blank username is reserved for server sockets.
		self.connectionDict[self.serverSocket] = ""
		self.connectionDict[self.downloadSocket] = ""

		checkDir = os.path.isdir(self.downloadDir)
		if not checkDir:
			os.mkdir(self.downloadDir)
			LOGGER.info(f"Created download directory in local folder {self.downloadDir}")
		
		LOGGER.info("Chat server started on port " + str(self.port))

		while True:
			readableSockets,_,_ = select.select(self.connectionDict.keys(),[],[])

			for sock in readableSockets:
				
				if sock == self.serverSocket:
					sockfd, addr = self.serverSocket.accept()
					self.connectionDict[sockfd] = ""
					LOGGER.info("Client (%s, %s) connected" % addr)
					sockfd.send(b"Connection successfully established")
				
				elif sock == self.downloadSocket:
					#Starts a new download thread if there's a connection on the download port so as to not block the whole server sending files.
					sockfd, addr = self.downloadSocket.accept()
					usrDownloadThread = DownloadThread(sockfd,self.downloadDir,True)
					usrDownloadThread.start()

				else:
					try:
						data = sock.recv(RECV_BUFFER)
						if not data:
							raise ConnectionResetError("Client forcefully closed the connection")
						else:
							request = json.loads(data.decode('utf-8'))
							if request["msgType"] == msgTypes.GCAST_MSG:
								localUsername = self.connectionDict[sock]
								LOGGER.info(f'Message from {localUsername}: {request["message"]}')
								self.globalcastMessage(f'{localUsername}: {request["message"]}',sock)

							elif request["msgType"] == msgTypes.LOGIN_MSG:
								LOGGER.info(f'User at {sock.getpeername()} logged in with the username {request["username"]}')
								self.connectionDict[sock] = request["username"]
								self.globalcastMessage(f'User "{request["username"]}" has joined the room')
							
							elif request["msgType"] == msgTypes.USER_REQ_MSG:
								self.userReqMessage(sock)
							
							elif request["msgType"] == msgTypes.UCAST_MSG:
								userToSendTo = request['username']
								message = request['message']
								self.unicastMessage(sock,userToSendTo,f"Unicast message from {userToSendTo}: {message}")
							
							elif request["msgType"] == msgTypes.SERVER_LS:
								self.sendLs(sock)
							
							elif request['msgType'] == msgTypes.QUIT:
								raise ConnectionResetError("Client requested to disconnect")

							else:
								sock.send("Invalid message".encode('utf-8'))


					except ConnectionResetError as e:
						self.globalcastMessage(formattedString(f"{self.connectionDict[sock]} is now offline"))
						LOGGER.info(f"{self.connectionDict[sock]} is offline")
						LOGGER.info(e)
						sock.close()
						if sock in self.connectionDict:
							del self.connectionDict[sock]
						continue

	def userReqMessage(self,sock):
		try:
			LOGGER.info(f'User "{self.connectionDict[sock]}" requested to see users online')
			usermsg = "Users currently online: " 
			usermsg += ', '.join(str(item) for item in list(self.connectionDict.values()) if item != "") #returns in format user1, user2 ..., usern
			sock.send(formattedString(usermsg).encode('utf-8'))
		except Exception as e:
			LOGGER.error(e)
			sock.send("Failed to send messsage")
			socket.close()
			if socket in self.connectionDict:
				del self.connectionDict[socket]
				

	def globalcastMessage(self,message,sock = None):
		for socket,username in self.connectionDict.items():
			if username != "" and socket != sock:
				try:
					LOGGER.info(f'Sending GCAST message "{message}" to {username}')
					socket.send(formattedString(message).encode('utf-8'))
				except Exception as e:
					LOGGER.error(e)
					socket.close()
					if socket in self.connectionDict:
						del self.connectionDict[socket]
						break
	
	def unicastMessage(self,sock,userToSendTo,message):
		if userToSendTo not in self.connectionDict.values():
			sock.send("User is currently not online".encode('utf-8'))
			return
			
		for socket, username in self.connectionDict.items():
			if username == userToSendTo:
				try:
					LOGGER.info(f"Sending UCAST message to {username}")
					socket.send(formattedString(message).encode('utf-8'))
				except Exception as e:
					LOGGER.error(e)
					sock.send("Failed to send messsage")
					socket.close()
					if socket in self.connectionDict:
						del self.connectionDict[socket]
						break
	
	def sendLs(self,sock):
		try:
			if sock not in self.connectionDict:
				raise Exception("User disconnected")
			
			if os.listdir(self.downloadDir) == []:
				LOGGER.warning(f'User "{self.connectionDict[sock]}" requested to see available files but none were available')
				sock.send(formattedString("No files currently on the server").encode('utf-8'))
			else:
				LOGGER.info(f'User "{self.connectionDict[sock]}" requested to see available files')
				msgToSend = formattedString("Files currently available: " + ', '.join(str(item) for item in os.listdir(self.downloadDir))).encode('utf-8')
				sock.send(msgToSend)
		
		except Exception as e:
			LOGGER.error(e)
			sock.close()


					

def main():
	try:
		try:
			port = int(sys.argv[1])
			if (port < 1024) or (port > 65535):
				#Ports below 1024 are usually reserved and shouldn't be used
				print("Port values should be between 1024-65535, please enter a valid port number")
				return
		except:
			print("Invalid input for port provided")
			return
	except IndexError:
		print("Invalid number of arguments provided")
		return
	server = Server(port)
	server.serverMain()
	
if __name__ == "__main__":
	main()
