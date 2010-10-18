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
import hashlib
import random
import string

site_root = 'http://skitch.ariaglassworks.com/'
users = ['ben', 'terrence']

page = '''
<html>
<head>
<style type="text/css">
.column{float:left;text-align:center;font-family:helvetica;}
.skitch_event{margin: 20px;}
.git_event{margin-top: 50px; margin-top: 50px;}
.git_message{font-size: 25pt; font-family: times new roman;}
.timestamp{text-align: left}
</style>
<script type="text/javascript" src="http://ajax.googleapis.com/ajax/libs/jquery/1.4.2/jquery.min.js"></script>
<script type="text/javascript">
function waitForMsg() {
    $.ajax({
      type: "GET", url: "/comet", async: true, cache: false, timeout: 50000,
      success: function(data) { eval(data); waitForMsg(); },
      error: function(XMLHttpRequest, textStatus, errorThrown) { if(textStatus != 'error') waitForMsg(); }
    });
};
/*
 * JavaScript Pretty Date
 * Copyright (c) 2008 John Resig (jquery.com)
 * Licensed under the MIT license.
 */
// Takes an ISO time and returns a string representing how
// long ago the date represents.
function prettyDate(time){
	var date = new Date(); date.setTime(time*1000);
	var diff = (((new Date()).getTime() - date.getTime()) / 1000),
		day_diff = Math.floor(diff / 86400);
			
	if ( isNaN(day_diff) || day_diff < 0 || day_diff >= 31 )
		return;
			
	return day_diff == 0 && (
			diff < 60 && "just now" ||
			diff < 120 && "1 minute ago" ||
			diff < 3600 && Math.floor( diff / 60 ) + " minutes ago" ||
			diff < 7200 && "1 hour ago" ||
			diff < 86400 && Math.floor( diff / 3600 ) + " hours ago") ||
		day_diff == 1 && "Yesterday" ||
		day_diff < 7 && day_diff + " days ago" ||
		day_diff < 31 && Math.ceil( day_diff / 7 ) + " weeks ago";
}
function prettyLinks(){
        var links = document.getElementsByClassName("timestamp");
        for ( var i = 0; i < links.length; i++ )
                if ( links[i].title ) {
                        var date = prettyDate(links[i].title);
                        if ( date )
                                links[i].innerHTML = date;
                }
}
prettyLinks();
setInterval(prettyLinks, 5000);
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
			' order by time desc ' + 
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
		copy = set(CometConnections.connections)
		for connection in copy:
			connection.tell(js)


class MainHandler(tornado.web.RequestHandler):
	def time_format(self, time):
		return str(time)
	def get(self):
		db = Database()
		for user in users:
			events = db.get(user=user, limit=10)
			formatted_events = ''
			for event in events:
				info = cPickle.loads(str(event[2]))
				if info['type'] == 'image':
					formatted_events += '<div class="skitch_event"><div class="timestamp" title="%s"></div><img src="http://skitch.ariaglassworks.com/%s" /></div>' % (self.time_format(event[3]), info['url'])
				else:
					formatted_events += '<div class="git_event"><div class="timestamp" title="%s"></div><div class="git_message">%s</div></div>' % (self.time_format(event[3]), info['message'])
			events = '<div class="column" style="width: %i%%;"><h1>%s</h1>%s</div>' % (100/len(users), user, formatted_events)
			self.write(page % events)

class GitHook(tornado.web.RequestHandler):
	def post(self):
		db = Database()
		key =  ''.join([random.choice(string.letters) for x in xrange(64)]) #TODO: use the git revision hash
		db.add(user=self.get_argument("user"), key=key, value=cPickle.dumps({'type': 'commit', 'message': self.get_argument("message")}))
		CometConnections.tellall('history.go(0);')

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
			updated = 0
			for new_file in current - existing:
				if not db.get(key=new_file):
					updated += 1
					user = new_file.split('/')[0]
					db.add(user=user, key=new_file, value=cPickle.dumps({'type': 'image', 'url':new_file}))
			if updated:
				CometConnections.tellall('history.go(0);')
			existing = current
			time.sleep(1)

application = tornado.web.Application([
	(r"/", MainHandler),
	(r"/comet", CometConnections),
	(r"/githook", GitHook),
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
	
