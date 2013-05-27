#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import webapp2
import jinja2
import os
import functools

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
        return {'name': 'david'}

    def post(self):
        # Create and store a document object
        # Redirect to link
        pass


class ChannelHandler(webapp2.RequestHandler):
    @render_template('channelconn.js')
    def get(self):
        self.response.headers['Content-Type'] = 'text/javascript'
        return {'presentation_key': 'o_key', 'token': 'token'}


class PDFViewHandler(webapp2.RequestHandler):
    def get(self):
        self.response.write('Hello world!')

app = webapp2.WSGIApplication([
                                  ('/', MainHandler),
                                  ('/channel.js', ChannelHandler),
                                  ('/viewer', PDFViewHandler)
                              ], debug=True)
