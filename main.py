#!/usr/bin/env python
import uuid
import webapp2
import jinja2
import os
import functools
from google.appengine.ext import db
from google.appengine.api import channel
import logging; logger = logging.getLogger(__name__)
import urllib
import json
import time
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers

SERVE_BLOB_URI = '/serve'

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')),
    extensions=['jinja2.ext.autoescape'])


def render_template(template_name):
    def my_decorator(infxn):
        template = JINJA_ENVIRONMENT.get_template(template_name)
        @functools.wraps(infxn)
        def outer(self, *args, **kwargs):
            result = infxn(self, *args, **kwargs)
            if result is not None:
                return self.response.write(template.render(result))
        return outer
    return my_decorator


def render_json(infxn):
    def outer(self, *args, **kwargs):
        self.response.headers['Content-Type'] = 'application/json'
        json_dict = infxn(self, *args, **kwargs)
        self.response.write(json.dumps(json_dict))
    return outer


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


class MainHandler(webapp2.RequestHandler):
    """Serves the home page"""
    @render_template('index.html')
    def get(self):
        t_vals = dict()
        error = self.request.get('error')
        if error:
            t_vals['error'] = error
        t_vals['blob_upload_url'] = blobstore.create_upload_url('/upload')

        return t_vals


class ChannelHandler(webapp2.RequestHandler):
    """Maintains HTTP Push aspect of presentations"""
    @render_json
    def get(self):
        """Returns current state of channel"""
        presentation_key = self.request.get('p_key')
        presentation = PresentationChannel.get(keys=presentation_key)
        return {'pageNum': presentation.page_num, 'timestamp': time.time()}

    def post(self):
        presentation_key = self.request.get('p_key')
        page_num = int(self.request.get('p'))
        client_id_source = self.request.get('client_id')
        presentation = PresentationChannel.get(keys=presentation_key)
        presentation.page_num = page_num
        presentation.put()
        # Broadcast page change to connected clients
        for client in presentation.channel_client_ids:
            if client != client_id_source:
                msg = {'pageNum': page_num, 'timestamp': time.time()}
                channel.send_message(client, json.dumps(msg))


class UploadPresentationHandler(blobstore_handlers.BlobstoreUploadHandler):
    """For uploading pdf presentations"""
    @render_template('presentation_creation.html')
    def post(self):
        upload_file = self.get_uploads("file")
        blob_info = upload_file[0]
        logger.info("Stored blob: filename=%s, key=%s, content_type=%s, size=%s" % (blob_info.filename, blob_info.key(),
                                                                                    blob_info.content_type, blob_info.size))
        if 'pdf' not in blob_info.content_type.lower():
            blob_info.delete()
            logger.info("Deleted blob: filename=%s, key=%s, content_type=%s, size=%s" % (blob_info.filename, blob_info.key(),
                                                                                    blob_info.content_type, blob_info.size))

            self.redirect('/?error=non-pdf')
            return None

        pdf_url = 'http://%s%s/%s' % (self.request.host, SERVE_BLOB_URI, blob_info.key())
        presentation = PresentationChannel(pdf_url=pdf_url)
        presentation.put()
        return {'presentation_url': 'http://%s%s' % (self.request.host, presentation.url())}


class ServePresentationHandler(blobstore_handlers.BlobstoreDownloadHandler):
    """Serves previously uploaded pdf presentations"""
    def get(self, resource):
        resource = str(urllib.unquote(resource))
        blob_info = blobstore.BlobInfo.get(resource)
        self.send_blob(blob_info)


class PDFPresentationHandler(webapp2.RequestHandler):
    """Serves the presentation room"""
    @render_template('viewer.html')
    def get(self):
        presentation_key = self.request.get('p_key')
        token, client_id = self._open_channel(presentation_key)
        logger.info("Created new client connection, token=%s" % token)
        return {'presentation_key': presentation_key, 'channel_token': token, 'client_id': client_id}

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


class About(webapp2.RequestHandler):
    @render_template('about.html')
    def get(self):
        return {}

app = webapp2.WSGIApplication([
                                  ('/about', About),
                                  ('/upload', UploadPresentationHandler),
                                  ('%s/([^/]+)?' % SERVE_BLOB_URI, ServePresentationHandler),
                                  ('/', MainHandler),
                                  ('/channel', ChannelHandler),
                                  ('/presentation', PDFPresentationHandler)
                              ], debug=True)
