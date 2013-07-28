#!/usr/bin/env python
import base64
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
import re
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
    pdf_name = db.StringProperty()
    created_datetime = db.DateTimeProperty(auto_now_add=True)
    page_num = db.IntegerProperty(default=1)
    channel_client_ids = db.StringListProperty()

    def presenter_url(self):
        q_string = urllib.urlencode({'p_key': self.key().name()})
        return '/presenter/%s?%s' % (self.pdf_name, q_string)

    def audience_url(self):
        q_string = urllib.urlencode({'p_key': self.key().name()})
        return '/audience/%s?%s' % (self.pdf_name, q_string)

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

def presentation_from_key(p_key):
    presentation = PresentationChannel.get_by_key_name(key_names=p_key)
    return presentation

class ChannelHandler(webapp2.RequestHandler):
    """Maintains HTTP Push aspect of presentations"""
    @render_json
    def get(self, action):
        """Returns current state of channel"""
        if action == 'page':
            presentation_key = self.request.get('p_key')
            presentation = presentation_from_key(presentation_key)
            return {'pageNum': presentation.page_num, 'timestamp': time.time()}

    def post(self, action):

        client_id_source = self.request.get('client_id')
        presentation_key = self.request.get('p_key')
        presentation = presentation_from_key(presentation_key)

        if action == 'page':
            page_num = int(self.request.get('p'))
            presentation.page_num = page_num
            presentation.put()
            msg = {'type': 'page', 'pageNum': page_num, 'timestamp': time.time()}
        elif action == 'laser_on':
            x = self.request.get('x')
            y = self.request.get('y')
            page_div_id = self.request.get('page_div_id')
            page_id = page_div_id[-1]
            msg = {'type': 'laser_on', 'x': x, 'y': y, 'page_div_id': page_div_id, 'pageId': page_id}
        elif action == 'laser_off':
            msg = {'type': 'laser_off'}

        # Broadcast page change to connected clients
        for client in presentation.channel_client_ids:
            if client != client_id_source:
                channel.send_message(client, json.dumps(msg))


class UploadPresentationHandler(blobstore_handlers.BlobstoreUploadHandler):
    """For uploading pdf presentations"""
    def _clean_pdf_name(self, file_name):
        MAX_FILENAME_CHARS = 100
        clean_file_name = file_name.lower().split('.pdf')[0]
        clean_file_name = clean_file_name.replace(' ', '-')
        clean_file_name = re.sub('[^a-zA-Z0-9_-]', '', clean_file_name)
        return clean_file_name[:MAX_FILENAME_CHARS]

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
        pdf_file_name = self._clean_pdf_name(blob_info.filename)
        key_name = unicode(base64.b64encode(uuid.uuid4().bytes).rstrip('='))
        presentation = PresentationChannel(key_name=key_name, pdf_url=pdf_url, pdf_name=pdf_file_name)
        presentation.put()
        return {'presenter_url': 'http://%s%s' % (self.request.host, presentation.presenter_url()),
                'audience_url': 'http://%s%s' % (self.request.host, presentation.audience_url())}


class ServePresentationHandler(blobstore_handlers.BlobstoreDownloadHandler):
    """Serves previously uploaded pdf presentations"""
    def get(self, resource):
        resource = str(urllib.unquote(resource))
        blob_info = blobstore.BlobInfo.get(resource)
        self.send_blob(blob_info)


class PDFPresentationHandler(webapp2.RequestHandler):
    """Serves the presentation room"""
    @render_template('viewer.html')
    def get(self, role=None, pdf_name=None):
        assert role in ['presenter', 'audience']
        presentation_key = self.request.get('p_key')
        presentation = presentation_from_key(presentation_key)
        token, client_id = self._open_channel(presentation)
        logger.info("Created new client connection, token=%s" % token)
        return {'role': role, 'pdf_url': presentation.pdf_url, 'presentation_key': presentation_key,
                'channel_token': token, 'client_id': client_id}

    def _open_channel(self, presentation):
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

class Test(webapp2.RequestHandler):
    @render_template('presentation_creation.html')
    def get(self):
                return {'presenter_url': 'http://%s' % ('localhost:9080/presenter/tsao_nigtp_y05_appt_letter_06_14_2013?p_key=V5X5Rm5IRnab4XTu32d%2BYA'),
                'audience_url': 'http://%s' % ('localhost:9080/audience/tsao_nigtp_y05_appt_letter_06_14_2013?p_key=V5X5Rm5IRnab4XTu32d%2BYA')}


app = webapp2.WSGIApplication([
                                  ('/about', About),
                                  ('/upload', UploadPresentationHandler),
                                  ('/', MainHandler),
                                  webapp2.Route('/channel/<action:(page)|(laser_on)|(laser_off)>', ChannelHandler),
                                  webapp2.Route('/<role:(presenter)|(audience)>/<pdf_name>', PDFPresentationHandler),
                                  ('%s/([^/]+)?' % SERVE_BLOB_URI, ServePresentationHandler),
                                  # ('/test', Test),
                              ], debug=False)
