import os
import select
import socket
import sys
import threading
import os
import errno
import json

from enum import IntEnum

RECV_BUFFER = 1024
PORTS_TO_SEARCH = 100

#message type enum mapping a type to an integer to avoid constantly keeping track of numbers in association to what they represent
class msgTypes(IntEnum):
	QUIT = 0
	GCAST_MSG = 1
	UCAST_MSG = 2
	LOGIN_MSG = 3
	USER_REQ_MSG = 4
	SERVER_LS = 5
	DOWNLOAD_MSG = 6
	HEADER_DOWNLOAD_ERR = 7
	HEADER_DOWNLOAD_START = 8

	def __str__(self):
		return self.name

class DownloadError(Exception):
	def __init__(self,message = ""):
		self.message = message
		super().__init__(self.message)

class DownloadThread(threading.Thread):
	def __init__(self,daemon, downloadLock, request,host,port):
		super(DownloadThread,self).__init__(daemon=daemon)
		self.clientDownloadSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.clientDownloadSocket.settimeout(2)
		self.downloadLock = downloadLock
		self.request = request
		self.host = host
		self.port = port + 1
	
	def run(self):
		self.downloadFile()

	def downloadFile(self):
		#Lock to make other threads wait for current thread to finish downloading.
		with self.downloadLock:
			try:
				localRequest = json.loads(self.request.decode('utf-8'))
				if localRequest['filename'] == "" or localRequest['filename'][0] == " ":
					raise DownloadError("Invalid filename provided")
				
			except Exception as e:
				print(e)
				return

			fileStr = f"./{localRequest['username']}/{localRequest['filename']}"

			with open(fileStr,'wb') as fileDescriptor:
				try:
					self.clientDownloadSocket.connect((self.host,self.port))
					self.clientDownloadSocket.send(self.request)
					#Get initial header to determine whether there were any errors or if the download is ready to start
					data = self.clientDownloadSocket.recv(RECV_BUFFER)

					request = json.loads(data.decode('utf-8'))
					if request['msgType'] == msgTypes.HEADER_DOWNLOAD_ERR:
						raise DownloadError(f"There was an error trying to download the file from the server: {request['message']}")
					elif request['msgType'] == msgTypes.HEADER_DOWNLOAD_START:
						while True:
							data = self.clientDownloadSocket.recv(RECV_BUFFER)
							if not data:
								fileDescriptor.close()
								break
							fileDescriptor.write(data)

				except DownloadError as e:
					print(e)
					fileDescriptor.close()
					os.remove(f"./{localRequest['username']}/{localRequest['filename']}")

				finally:	
					self.clientDownloadSocket.close()
					if not fileDescriptor.closed:
						fileDescriptor.close()


class ServerThread(threading.Thread):
	def __init__(self,daemon,clientPort,username,host,port):
		super(ServerThread,self).__init__(daemon=daemon)
		self.clientPort = clientPort
		self.serverReadyEvent = threading.Event()
		self.username = username
		self.host = host
		self.port = port
		self.downloadLock = threading.Lock()

	def run(self):
		self.thread()

	def thread(self):
		internalSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		clientSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		clientSocket.settimeout(2)

		internalSocket.bind((self.host,self.clientPort))
		internalSocket.listen(1)

		#sets a threading event so that ClientThread can connect on the internal socket for communication
		self.serverReadyEvent.set()


		try :
			clientSocket.connect((self.host, self.port))
		except Exception as e :
			print(e)
			return

		socketsList = [internalSocket,clientSocket]

		try:
			while True:
				readable, _, _ = select.select(socketsList, [], [])

				for readableSocket in readable:
					if readableSocket == internalSocket:
						#When the internal socket connects, the application is ready to recieve input, The application then requests to login.
						internalclientSocket, _ = internalSocket.accept()
						socketsList.append(internalclientSocket)
						LOGIN_MSG = {"msgType": int(msgTypes.LOGIN_MSG),"username" : self.username}
						clientSocket.send(json.dumps(LOGIN_MSG).encode('utf-8'))
					
					
					elif readableSocket == clientSocket:
						data = readableSocket.recv(RECV_BUFFER)
						if not data :
							raise Exception("Disconnected from chat server")
						else:
							print(data.decode('utf-8'))
					
					else:
						data = readableSocket.recv(RECV_BUFFER)
						request = json.loads(data)
						if data:
							if request['msgType'] == msgTypes.QUIT:
								clientSocket.send(data)
								socketsList.remove(readableSocket)
								readableSocket.close()
								internalSocket.close()
								raise Exception("Quitting...")
							elif request['msgType'] == msgTypes.DOWNLOAD_MSG:
								downloadThread = DownloadThread(True,self.downloadLock,data,self.host,self.port)
								downloadThread.start()

							else:
								#Messages other than QUIT or DOWNLOAD_MSG are sent here as no further handling needs to be done.
								clientSocket.send(data)
						else:
							socketsList.remove(readableSocket)
							readableSocket.close()
							internalSocket.close()
							raise Exception("Internal socket disconnected, Quitting...")
					
		except Exception as e:
			print(e)

		finally:
			for s in socketsList:
				s.close()

	
	@staticmethod
	def checkPorts(basePort):
		#Attempts to find a free port for the internalSocket to use. Returns a free port when one is found
		for i in range(PORTS_TO_SEARCH):
			s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			try:        
				s.bind(("127.0.0.1", basePort + i))
			except socket.error as e:
				if e.errno == errno.EADDRINUSE:
					continue
			else:
				s.close()
				return basePort + i

				

class ClientThread(threading.Thread):
	def __init__(self,daemon,clientPort,username,host,serverReadyEvent):
		super(ClientThread,self).__init__(daemon=daemon)
		self.host = host
		self.clientPort = clientPort
		self.serverReadyEvent = serverReadyEvent
		self.username = username

	def run(self):
		self.thread()

	def thread(self):
		#Waits for the earlier event mentioned to be set to connect to the internal socket
		self.serverReadyEvent.wait()

		self.printOptions()
		internalSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
		
			internalSocket.connect((self.host, self.clientPort))
		
			while True:
				
				message = input()
				if len(message) == 0:
					continue
				if message[0] == "/":

					if message[1:] == "ucast":
						username = input("Who would you like to send a message to?:")
						msgStr = input("Input the message you would like to send:")
						message = {"msgType":msgTypes.UCAST_MSG,"username":username, "message":msgStr}
						message = json.dumps(message)
						internalSocket.send(message.encode('utf-8'))
						continue

					elif message[1:] == "users":
						message = {"msgType":msgTypes.USER_REQ_MSG}
						message = json.dumps(message)
						internalSocket.send(message.encode('utf-8'))
						continue

					elif message[1:] == "quit":
						message = {"msgType":msgTypes.QUIT}
						message = json.dumps(message)
						internalSocket.send(message.encode('utf-8'))
						break

					elif message[1:] == "ls":
						message = {"msgType":msgTypes.SERVER_LS}
						message = json.dumps(message)
						internalSocket.send(message.encode('utf-8'))
						continue

					elif message[1:] == "get":
						filename = input("Input filename:")
						message = {"msgType":msgTypes.DOWNLOAD_MSG,"filename":filename,"username":self.username}
						message = json.dumps(message)
						internalSocket.send(message.encode('utf-8'))
						continue
					elif message[1:] == "help":
						self.printOptions()
						continue
					else:
						continue
			
				message = {"msgType":msgTypes.GCAST_MSG,"message":message}
				message = json.dumps(message)
				internalSocket.send(message.encode('utf-8'))
					

		except OSError as e:
			if e.errno == errno.EPIPE:
				pass
			else:
				print(e)

		finally:
			internalSocket.close()
	
	def printOptions(self):
		print("""\nClient options:
/ucast - Send a message to a specific user
/users - See which users are currently online
/quit - Quit the messaging app
/ls - See which files are avaliable for downloading
/get - Download file from the server
/help - View these options again\n""")

def main():
	try:
		username = sys.argv[1]
		host = sys.argv[2]
		try:
			port = int(sys.argv[3])
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

	clientPort = ServerThread.checkPorts(port+2)
 
	if not os.path.isdir(f"./{username}/"):
		os.mkdir(f'./{username}/')
	
	server = ServerThread(True,clientPort,username,host,port)
	client = ClientThread(True,clientPort,username,host,server.serverReadyEvent)
	server.start()
	client.start()

	server.join()
	client.join()

if __name__ == "__main__":
	main()
