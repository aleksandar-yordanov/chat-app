CLI Instant messenger:

Server setup:
To use server.py, run the python file with a port as an argument

Format: python server.py [PORT]

Example: python server.py 5000

Notes:
- When first ran, the server will create a downloads directory called ServerDownloads, place any files you'd like users to be able to download there

- The server will also create a server.log file where you are able to view any logs that the server produces. - This does not get cleared when the server is reran

- Port values are required to be between 1024-65535



Client setup:
To use client.py, run the python file with the arguments, username, hostname/ip address and port

Format: python client.py [USERNAME] [HOSTNAME] [PORT]

Example: python client.py exampleUsername 127.0.0.1 5000

Notes:
- When files are downloaded they are placed in a folder named after the username inputted
