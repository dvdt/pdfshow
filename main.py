#!/usr/bin/env python
import uuid
import webapp2
import jinja2
import os
import functools
# import urllib2
from google.appengine.ext import db
from google.appengine.api import channel
import logging; logger = logging.getLogger(__name__)
import urllib
import json
import time

class PresentationChannel(db.Model):
    pdf_url = db.LinkProperty()
    created_datetime = db.DateTimeProperty(auto_now_add=True)
    page_num = db.IntegerProperty(default=1)
    channel_client_ids = db.StringListProperty()

    def url(self):
        q_string = urllib.urlencode({'p_key': self.key(), 'pdf_url': self.pdf_url})
        return '/presentation?%s' % q_string

    # TODO: make this an atomic operation
    def add_channel_client_id(self, client_id):
        """Adds a new client to the presentation"""
        if client_id not in self.channel_client_ids:
            self.channel_client_ids.append(client_id)
        self.put()

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')),
    extensions=['jinja2.ext.autoescape'])


def render_template(template_name):
    def my_decorator(infxn):
        template = JINJA_ENVIRONMENT.get_template(template_name)
        @functools.wraps(infxn)
        def outer(self, *args, **kwargs):
            return self.response.write(template.render(infxn(self, *args, **kwargs)))
        return outer
    return my_decorator


class MainHandler(webapp2.RequestHandler):
    @render_template('index.html')
    def get(self):
        error = self.request.get('error')
        return {}

    def post(self):
        # Create and store a document object
        # Redirect to link
        pass


class ChannelHandler(webapp2.RequestHandler):
    def get(self):
        """Returns current state of channel"""
        presentation_key = self.request.get('p_key')
        presentation = PresentationChannel.get(keys=presentation_key)
        self.response.headers['Content-Type'] = 'application/json'
        msg = {'pageNum': presentation.page_num}
        self.response.write(json.dumps(msg))

    def post(self):
        presentation_key = self.request.get('p_key')
        page_num = int(self.request.get('p'))
        client_id_source = self.request.get('client_id')
        presentation = PresentationChannel.get(keys=presentation_key)
        presentation.page_num = page_num

        # Broadcast page change to connected clients
        for client in presentation.channel_client_ids:
            if client != client_id_source:
                msg = {'pageNum': page_num, 'timestamp': time.time()}
                channel.send_message(client, json.dumps(msg))

class PDFPresentationHandler(webapp2.RequestHandler):
    @render_template('viewer.html')
    def get(self):
        presentation_key = self.request.get('p_key')
        token, client_id = self._open_channel(presentation_key)
        logger.info("Created new client connection, token=%s" % token)
        return {'presentation_key': presentation_key, 'channel_token': token, 'client_id': client_id}

    @render_template('presentation_creation.html')
    def post(self):
        pdf_url = self.request.get('pdf-url')
        presentation = PresentationChannel(pdf_url=pdf_url)
        presentation.put()
        return {'presentation_url': presentation.url()}

    def _open_channel(self, presentation_key):
        presentation = PresentationChannel.get(keys=presentation_key)
        client_id = self._get_client_id()
        presentation.add_channel_client_id(client_id)
        token = channel.create_channel(client_id)
        return token, client_id

    def _get_client_id(self):
        """For now, return a random string
        """
        return str(uuid.uuid4())

app = webapp2.WSGIApplication([
                                  ('/', MainHandler),
                                  ('/channel', ChannelHandler),
                                  ('/presentation', PDFPresentationHandler)
                              ], debug=True)
