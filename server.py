import tornado.httpserver
import tornado.ioloop
import tornado.web
import sqlite3
import time
import re
import os
import cPickle
import threading
import signal
import sys
import hashlib
import random
import string

import config
#skitch_root = 'http://skitch.google.com/'
#skitch_path = '/home/skitch'
# users = [{'username': 'John', 'fullname': 'John Smith'}]

# Example githook (commit-msg)
#!/usr/bin/python
#import sys
#import subprocess
#import urllib
#import os
#  
#commit = subprocess.Popen(["/usr/bin/head", "-n", "1", sys.argv[1]], stdout=subprocess.PIPE).communicate()[0]
#name = (get a username somehow up to you)
#os.system('curl -d "%s" http://river.google.com/githook' % urllib.urlencode({'message': commit, 'user': name}))

page = '''
<html>
<head>
<title>not 4chan</title>
<style type="text/css">
body{padding: 0px; border: 0px;}
.column{float:left;text-align:center;font-family:helvetica;-webkit-box-sizing:border-box;padding:50px;}
.skitch_event{width: 100%%; margin-top: 50px;}
.skitch_event img {width: 100%%;}
.skitch_event img:hover {width: auto;}
.git_event{width: 100%%;margin-top: 50px; margin-top: 50px;}
.git_message{font-size: 25pt; font-family: times new roman;}
.timestamp{text-align: left; font-style:italic; margin:20px; }
.column{border-right: 1px dashed black;}
.column:last-child{border-left: 0px solid black;}
.tags{position: fixed; background: #666; width: 100%%; top: 0px; left: 0px; border-bottom: #ddd 2px solid; padding: 10px;}
.tags a{color: #ddd; margin-right: 10px; text-decoration: none; font-family: helvetica;text-shadow:0 1px 0 #333;}
.tags a.selected{color: #fff; font-weight: bold;}
.tags a:hover{color: #aaa;}
.title { position: absolute; top: 5px; right: 5px; font-size: 25px; color: #444; font-family: helvetica; margin-right: 25px;}
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
setInterval(prettyLinks, 5000);
window.onload = function(){ prettyLinks(); setTimeout('waitForMsg()', 1); };
</script>
</head>
<body>%s</body>
</html>'''

class Database(object):
	table1 = """CREATE TABLE IF NOT EXISTS events (
            key varchar(250) primary key,
            user varchar(250),
            value text,
            time integer,
	    disabled integer
        );"""

	table2 = """
	CREATE TABLE IF NOT EXISTS tags (
            key varchar(250),
            tag text
        );"""

	def __init__(self):
		self.conn = sqlite3.connect('river.db')
        	c = self.conn.cursor()
        	c.execute(Database.table1)
        	c.execute(Database.table2)

	def add(self, user, key, value, timestamp=None):
		self.conn.execute('insert or ignore into events values (?, ?, ?, ?, 0)', (key, user, value, timestamp or time.time()))
		tags = [tag[1:-1] for tag in re.findall("\([^)]+\)", key)] + [user]
		print tags
		for t in tags:
			self.conn.execute('insert or ignore into tags values (?, ?)', (key, t)) 
		self.conn.commit()

	def get(self, user=None, key=None, limit=None, tag=None):
		c = self.conn.cursor()
		rows = c.execute('select * from events' + 
			(', tags ' if tag else '') +
			(' where disabled=0 ')
			+ (' and events.key = tags.key and tags.tag = :tag ' if tag else '')
			 +(' and ' if user or key else '') +
			(' user=:user ' if user else '') + 
			(' and ' if (user and key) else '') +
			(' key=:key ' if key else '') + 
			' order by time desc ' + 
			(' limit :limit' if limit else '') , 
			{'user': user, 'key': key, 'limit': limit, 'tag': tag })
		return rows.fetchall()

	def tags(self):
		c = self.conn.cursor()
		rows = c.execute('select tag from tags group by tag order by count(*) desc')
		return [r[0] for r in rows.fetchall()]

class CometConnections(tornado.web.RequestHandler):
	connections = set({})

	@tornado.web.asynchronous
	def get(self):
		CometConnections.connections.add(self)

	def tell(self, js):
		if self in CometConnections.connections:
			CometConnections.connections.remove(self)
		self.write(js)
		self.finish()

	@staticmethod
	def tellall(js):
		copy = set(CometConnections.connections)
		for connection in copy:
			try:
				connection.tell(js)
			except IOError:
				if connection in CometConnections.connections:
					CometConnections.connections.remove(connection)


class MainHandler(tornado.web.RequestHandler):
	def time_format(self, time):
		return str(time)
	def get(self, tag=None):
		db = Database()
		pagebody = '<div class="tags"><a href="/">[all]</a>' + ' '.join(['<a class="%s" href="/%s">%s</a>' % ("selected" if t == tag else "", t, t) for t in db.tags()]) + '<div class="title">' + tag + ' : not 4chan</div></div>'
		for user in config.users:
			if tag:
				events = db.get(user=user['username'], tag=tag)
			else:
				events = db.get(user=user['username'], limit=10)
			formatted_events = ''
			for event in events:
				info = cPickle.loads(str(event[2]))
				if info['type'] == 'image':
					formatted_events += '<div class="skitch_event"><div class="timestamp" title="%s"></div><img src="%s%s" /></div>' % (self.time_format(event[3]), config.skitch_root, info['url'])
				else:
					formatted_events += '<div class="git_event"><div class="timestamp" title="%s"></div><div class="git_message">&ldquo;%s&rdquo;</div></div>' % (self.time_format(event[3]), info['message'])
			pagebody += '<div class="column" style="width: %i%%;"><h1>%s</h1>%s</div>' % (100/len(config.users), user['fullname'], formatted_events)
		self.write(page % pagebody)

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
			current	= set([file[len(self.path) + 1:] for file in files if file[-4:] == ".jpg" or file[-4:] == ".png"])
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
	(r"/comet", CometConnections),
	(r"/githook", GitHook),
	(r"/(?P<tag>.*)", MainHandler),
])

if __name__ == "__main__":
	fw = FileWatcher(config.skitch_path)
	fw.start()

	http_server = tornado.httpserver.HTTPServer(application)
	http_server.listen(9876)
	tn = tornado.ioloop.IOLoop.instance()
	try:
		tn.start()
	except KeyboardInterrupt:
		fw.running = False
	
