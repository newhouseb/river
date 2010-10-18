import tornado.httpserver
import tornado.ioloop
import tornado.web
import sqlite3
import time
import os
import cPickle
import threading
import signal
import sys

site_root = 'http://skitch.ariaglassworks.com/'
users = ['ben', 'terrence']

page = '''
<html>
<head>
<style type="text/css">
.column{float:left;text-align:center;font-family:helvetica;}
.skitch_event{margin: 20px;}
</style>
<script type="text/javascript">
function waitForMsg() {
    $.ajax({
      type: "GET", url: "/comet", async: true, cache: false, timeout: 50000,
      success: function(data) { eval(data); waitForMsg(); },
      error: function(XMLHttpRequest, textStatus, errorThrown) { waitForMsg(); }
    });
};
window.onload = function(){ setTimeout('waitForMsg()', 1); };
</script>
</head>
<body>%s</body>
</html>'''

class Database(object):
	table = """CREATE TABLE IF NOT EXISTS events (
            key varchar(250) primary key,
            user varchar(250),
            value text,
            time integer
        );"""

	def __init__(self):
		self.conn = sqlite3.connect('river.db')
        	c = self.conn.cursor()
        	c.execute(Database.table)

	def add(self, user, key, value, timestamp=None):
		self.conn.execute('insert or ignore into events values (?, ?, ?, ?)', (key, user, value, timestamp or time.time()))
		self.conn.commit()

	def get(self, user=None, key=None, limit=None):
		c = self.conn.cursor()
		rows = c.execute('select * from events ' + 
			(' where ' if user or key else '') +
			(' user=:user ' if user else '') + 
			(' and ' if (user and key) else '') +
			(' key=:key ' if key else '') + 
			' order by time' + 
			(' limit :limit' if limit else '') , 
			{'user': user, 'key': key, 'limit': limit })
		return rows.fetchall()

class CometConnections(tornado.web.RequestHandler):
	connections = set({})

	@tornado.web.asynchronous
	def get(self):
		CometConnections.connections.add(self)

	def tell(self, js):
		CometConnections.connections.remove(self)
		self.write(js)
		self.finish()

	@staticmethod
	def tellall(js):
		for connection in CometConnections.connections:
			connection.tell(js)


class MainHandler(tornado.web.RequestHandler):
	def get(self):
		db = Database()
		for user in users:
			events = db.get(user=user, limit=10)
			formatted_events = ''
			for event in events:
				info = cPickle.loads(str(event[2]))
				if info['type'] == 'image':
					formatted_events += '<div class="skitch_event"><img src="http://skitch.ariaglassworks.com/%s" /></div>' % info['url']
				else:
					formatted_events += ''
			events = '<div class="column" style="width: %i%%;"><h1>%s</h1>%s</div>' % (100/len(users), user, formatted_events)
			self.write(page % events)

class GitHook(tornado.web.RequestHandler):
	def post(self):

		pass


class FileWatcher(threading.Thread):
	def __init__(self, path):
		super(FileWatcher, self).__init__()
		self.path = path
		self.running = True

	def run(self):
		db = Database()
		existing = set([])
		while self.running == True:
			directories = os.walk(self.path)
			files = []
			for dirpath, dirnames, filenames in directories:
				for filename in filenames:
					files.append(os.path.join(dirpath, filename))
			current	= set([file[len(self.path) + 1:] for file in files if file[-4:] == ".jpg"])
			for new_file in current - existing:
				if not db.get(key=new_file):
					user = new_file.split('/')[0]
					db.add(user=user, key=new_file, value=cPickle.dumps({'type': 'image', 'url':new_file}))
			existing = current
			time.sleep(1)

application = tornado.web.Application([
	(r"/", MainHandler),
	(r"/comet", CometConnections),
])

if __name__ == "__main__":
	fw = FileWatcher("/home/skitch")
	fw.start()

	http_server = tornado.httpserver.HTTPServer(application)
	http_server.listen(8888)
	tn = tornado.ioloop.IOLoop.instance()
	try:
		tn.start()
	except KeyboardInterrupt:
		fw.running = False
	
