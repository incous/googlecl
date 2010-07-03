# Copyright (C) 2010 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Basic service extensions for the gdata python client library for use on
  the command line."""


import gdata.service
import googlecl
import re


DATE_FORMAT = '%Y-%m-%d'


class Error(Exception):
  """Base error for GoogleCL exceptions."""
  pass

class LeftoverData(Warning):
  """Data left on server because of max_results and cap_results settings."""
  pass


class BaseServiceCL(gdata.service.GDataService):

  """Extension of gdata.GDataService specific to GoogleCL."""

  def _set_params(self, section):
    """Set some basic attributes common to all instances."""
    LARGE_MAX_RESULTS = 10000
    # Because each new xxxServiceCL class should use the more specific
    # superclass's __init__ function, don't define one here.
    self.source = 'GoogleCL'
    self.client_id = 'GoogleCL'
    # To resolve Issue 367
    # http://code.google.com/p/gdata-python-client/issues/detail?id=367
    self.ssl = False
    
    # Some new attributes, not inherited.
    self.use_regex = googlecl.get_config_option(section, 'regex',
                                                default=True, type=bool)
    self.prompt_for_tags = googlecl.get_config_option(section, 'tags_prompt',
                                                      default=False, type=bool)
    self.prompt_for_delete = googlecl.get_config_option(section,
                                                        'delete_prompt',
                                                        default=True,
                                                        type=bool)
    self.cap_results = googlecl.get_config_option(section,
                                                  'cap_results',
                                                  default=False,
                                                  type=bool)
    self.max_results = googlecl.get_config_option(section,
                                                  'max_results',
                                                  default=LARGE_MAX_RESULTS,
                                                  type=int)
    # Prevent user from shooting self in foot...
    if not self.cap_results and self.max_results < LARGE_MAX_RESULTS:
      self.max_results = LARGE_MAX_RESULTS

  def delete(self, entries, entry_type, delete_default):
    """Extends Delete to handle a list of entries.
    
    Keyword arguments:
      entries: List of entries to delete.
      entry_type: String describing the thing being deleted (e.g. album, post).
      delete_default: Whether or not the default action should be deletion.
      
    """
    if delete_default and self.prompt_for_delete:
      prompt_str = '(Y/n)'
    elif self.prompt_for_delete:
      prompt_str = '(y/N)'
    for item in entries:
      if self.prompt_for_delete:
        delete_str = raw_input('Are you SURE you want to delete %s "%s"? %s: ' %
                               (entry_type, item.title.text, prompt_str))
        if not delete_str:
          delete = delete_default
        else:
          delete = delete_str.lower() == 'y'
      else:
        delete = True
      if delete:
        try:
          gdata.service.GDataService.Delete(self, item.GetEditLink().href)
        except gdata.service.RequestError, err:
          print 'Could not delete ' + entry_type + ': ' + str(err)

  Delete = delete

  def get_email(self, _uri=None):
    """Get the email address that has the OAuth access token.

    Uses the "Email address" scope to return the email address the user
    was logged in as when he/she authorized the OAuth request token.

    Keyword arguments:
      uri: Uri to get data from. Should only be used for redirects.

    Returns:
      Full email address ('schmoe@domain.wtf') of the account with access.

    """
    # Use request instead of Get to avoid the attempts to parse from xml.
    server_response = self.request('GET',
                           _uri or 'https://www.googleapis.com/userinfo/email',
                           headers={'Content-Type': 'text/plain'})
    result_body = server_response.read()

    if server_response.status == 200:
      try:
        from urlparse import parse_qs
        parse_func = parse_qs
      except ImportError:
        # parse_qs was moved to urlparse from cgi in python2.6
        import cgi
        parse_func = cgi.parse_qs
      param_dict = parse_func(result_body)
      email = param_dict['email'][0]
    # This block copied (with some modification) from GDataService (2.0.10)
    elif server_response.status == 302:
      if redirects_remaining > 0:
        location = (server_response.getheader('Location') or
                    server_response.getheader('location'))
        if location is not None:
          return BaseServiceCL.get_email(location)
        else:
          raise gdata.service.RequestError, {'status': server_response.status,
                'reason': '302 received without Location header',
                'body': result_body}
      else:
        raise gdata.service.RequestError, {'status': server_response.status,
              'reason': 'Redirect received, but redirects_remaining <= 0',
              'body': result_body}
    else:
      raise gdata.service.RequestError, {'status': server_response.status,
            'reason': server_response.reason, 'body': result_body}
    return email

  def get_entries(self, uri, title=None, converter=None):
    """Get a list of entries from a feed uri.
    
    Keyword arguments:
      uri: URI to get the feed from.
      title: String to use when looking for entries to return. Will be compared
             to entry.title.text, using regular expressions if self.use_regex.
             (Default None for all entries from feed)
      converter: Converter to use on the feed. If specified, will be passed into
                 the GetFeed method. If None (default), GetFeed will be called
                 without the converter argument being passed in.
    Returns:
      List of entries.
    
    """
    import warnings
    uri = set_max_results(uri, self.max_results)
    try:
      if converter:
        feed = self.GetFeed(uri, converter=converter)
      else:
        feed = self.GetFeed(uri)
    except gdata.service.RequestError, err:
      print 'Failed to get entries: ' + str(err)
      return []
    all_entries = feed.entry
    if feed.GetNextLink():
      if self.cap_results:
        warnings.warn('Leaving data that matches query on server.' +
                      ' Increase max_results or set cap_results to False.',
                      LeftoverData, stacklevel=2)
      else:
        while feed and feed.GetNextLink():
          feed = self.GetNext(feed)
          if feed:
            all_entries.extend(feed.entry)
    if not title:
      return all_entries
    if self.use_regex:
      return [entry for entry in all_entries 
              if entry.title.text and re.match(title,entry.title.text)]
    else:
      return [entry for entry in all_entries if title == entry.title.text]

  GetEntries = get_entries

  def get_single_entry(self, uri_or_entry_list, title=None, converter=None):
    """Return exactly one entry.
    
    Uses GetEntries to retrieve the entries, then asks the user to select one of
    them by entering a number.
    
    Keyword arguments:
      uri_or_entry_list: URI to get feed from (See get_entries) or list of
                         entries to select from.
      title: Title to match on. See GetEntries. (Default None).
      converter: Conversion function to apply to feed. See GetEntries.
    
    Returns:
      None if there were no matches, or one entry matching the given title.
    
    """
    if not uri_or_entry_list:
      return None

    if isinstance(uri_or_entry_list, basestring):
      entries = self.GetEntries(uri_or_entry_list, title, converter)
    elif isinstance(uri_or_entry_list, list):
      entries = uri_or_entry_list
    else:
      raise Error('Got unexpected type for uri_or_entry_list!')

    if not entries:
      return None
    if len(entries) == 1:
      return entries[0]
    elif len(entries) > 1:
      print 'More than one match for title ' + (title or '')
      for num, entry in enumerate(entries):
        print '%i) %s' % (num, entry.title.text)
      selection = -1
      while selection < 0 or selection > len(entries)-1: 
        selection = int(raw_input('Please select one of the items by number: '))
      return entries[selection]

  GetSingleEntry = get_single_entry

  def is_token_valid(self, test_uri=None):
    """Check that the token being used is valid.
    
    Keyword arguments:
      test_uri: URI to pass to self.Get(). Default None (raises error).
      
    Returns:
      True if Get was successful, False if Get raised an exception with the
      string 'Token invalid' in its body, and raises any other exceptions.
    
    """
    if not test_uri:
      raise Error('No uri to test token with!' +
                  '(was is_token_valid extended?)')
    test_uri = set_max_results(test_uri, 1) 
    try:
      # Try to limit the number of results we get.
      self.Get(test_uri)
    except gdata.service.RequestError, err:
      # If the complaint is NOT about the token, print the error message.
      if err.args[0]['body'].lower().find('token invalid') == -1:
        print 'Token invalid! ' + str(err)
      return False
    else:
      return True

  IsTokenValid = is_token_valid

  def request_access(self, domain, scopes=None):
    """Do all the steps involved with getting an OAuth access token.
    
    Keyword arguments:
      domain: Domain to request access for.
              (Sets the hd query parameter for the authorization step).
      scopes: String or list/tuple of strings describing scopes to request
              access to. Default None for default scope of service.
    Returns:
      True if access token was succesfully retrieved and set, otherwise False.
    
    """
    import ConfigParser
    import webbrowser
    # Installed applications do not have a pre-registration and so follow
    # directions for unregistered applications
    self.SetOAuthInputParameters(gdata.auth.OAuthSignatureMethod.HMAC_SHA1,
                                 consumer_key='anonymous',
                                 consumer_secret='anonymous')
    display_name = 'GoogleCL'
    fetch_params = {'xoauth_displayname':display_name}
    # First and third if statements taken from
    # gdata.service.GDataService.FetchOAuthRequestToken.
    # Need to do this detection/conversion here so we can add the 'email' API
    if not scopes:
      scopes = gdata.service.lookup_scopes(self.service)
    if isinstance(scopes, tuple):
      scopes = list(scopes)
    if not isinstance(scopes, list):
      scopes = [scopes,]
    scopes.extend(['https://www.googleapis.com/auth/userinfo#email'])
    try:
      request_token = self.FetchOAuthRequestToken(scopes=scopes,
                                                  extra_parameters=fetch_params)
    except gdata.service.FetchingOAuthRequestTokenFailed, err:
      print err[0]['body'].strip() + '; Request token retrieval failed!'
      return False
    auth_params = {'hd': domain}
    auth_url = self.GenerateOAuthAuthorizationURL(request_token=request_token,
                                                  extra_params=auth_params)
    try:
      try:
        browser_str = googlecl.CONFIG.get('GENERAL', 'auth_browser')
      except ConfigParser.NoOptionError:
        browser = webbrowser.get()
      else:
        browser = webbrowser.get(browser_str)
      browser.open(auth_url)
    except webbrowser.Error, err:
      print 'Failed to launch web browser: ' + str(err)
    message = 'Please log in and/or grant access via your browser at ' +\
              auth_url + ' then hit enter.'
    raw_input(message)
    # This upgrades the token, and if successful, sets the access token
    try:
      self.UpgradeToOAuthAccessToken(request_token)
    except gdata.service.TokenUpgradeFailed:
      print 'Token upgrade failed! Could not get OAuth access token.'
      return False
    else:
      return True

  RequestAccess = request_access


def set_max_results(uri, max):
  """Set max-results parameter if it is not set already."""
  max_str = str(max)
  if uri.find('?') == -1:
    return uri + '?max-results=' + max_str
  else:
    if uri.find('max-results') == -1:
      return uri + '&max-results=' + max_str
    else:
      return uri


# The use of login_required has been deprecated - all tasks now require
# logging in, and google.py does not check whether or not a task
# says otherwise.
class Task(object):
  
  """A container of requirements.
  
  Each requirement matches up with one of the attributes of the option parser
  used to parse command line arguments. Requirements are given as lists.
  For example, if a task needs to have attr1 and attr2 and either attr3 or 4,
  the list would look like ['attr1', 'attr2', ['attr3', 'attr4']]
  
  """
  
  def __init__(self, description, callback=None, required=[], optional=[],
               login_required=True, args_desc=''):
    """Constructor.
    
    Keyword arguments:
      description: Description of what the task does.
      callback: Function to use to execute task.
                (Default None, prints a message instead of running)
      required: Required options for the task. (Default None)
      optional: Optional options for the task. (Default None)
      login_required: If logging in with a username is required to do this task.
                If True, can typically ignore 'user' as a required attribute. 
                (Default True)
      args_desc: Description of what the arguments should be. 
                 (Default '', for no arguments necessary for this task)
      
    """
    if isinstance(required, basestring):
      required = [required]
    if isinstance(optional, basestring):
      optional = [optional]
    self.description = description
    self.run = callback or self._not_impl
    self.required = required
    self.optional = optional
    self.login_required = login_required
    # Take the "required" list, join all the terms by the following rules:
    # 1) if the term is a string, leave it.
    # 2) if the term is a list, join it with the ' OR ' string.
    # Then join the resulting list with ' AND '.
    if self.required:
      req_str = ' AND '.join(['('+' OR '.join(a)+')' if isinstance(a, list) \
                              else a for a in self.required])
    else:
      req_str = 'none'
    if self.optional:
      opt_str = ' Optional: ' + str(self.optional)[1:-1].replace("'", '')
    else:
      opt_str = ''
    if args_desc:
      args_desc = ' Arguments: ' + args_desc
    self.usage = 'Requires: ' + req_str + opt_str + args_desc
    
  def is_optional(self, attribute):
    """See if an attribute is optional"""
    # No list of lists in the optional fields
    if attribute in self.optional:
      return True
    return False
  
  def requires(self, attribute, options=None):
    """See if a attribute is required.
    
    Keyword arguments:
      attribute: Attribute in question.
      options: Object with attributes to check for. If provided, intelligently
               checks if the attribute is necessary, given the attributes
               already in options. (Default None)
    Returns:
      True if the attribute is always required.
      False or [] if the attribute is never required
      If options is provided, a list of lists, where each sublist contains the
        name of the attribute that is required. For example, if either 'title'
        or 'query' is required, will return [['title','query']] 
    
    """
    # Get a list of all the sublists that contain attribute
    choices = [sublist for sublist in self.required
               if isinstance(sublist, list) and attribute in sublist]
    if options:
      if attribute in self.required:
        return not bool(getattr(options, attribute))
      if choices:
        for sublist in choices:
          for item in sublist:
            if getattr(options, item):
              return False
        return True
    else:
      if attribute in self.required:
        return True
      else:
        return choices

  def _not_impl(self, *args):
    """Just use this as a place-holder for Task callbacks."""
    print 'Sorry, this task is not yet implemented!'


class BaseEntryToStringWrapper(object):
  """Wraps GDataEntries to easily get human-readable data."""
  def __init__(self, gdata_entry,
               intra_property_delimiter='',
               label_delimiter=' '):
    """Constructor.

    Keyword arguments:
      gdata_entry: The GDataEntry to extract data from.
      intra_property_delimiter: Delimiter to distinguish between multiple
                   values in a single property (e.g. multiple email addresses).
                   Default '' (there will always be at least one space).
      label_delimiter: String to place in front of a label for intra-property
                       values. For example, for a contact with multiple phone
                       numbers, ':' would yield "Work:<number> Home:<number>"
                       Default ' ' (there is no whitespace between label and
                       value if it is not specified).
                       Set as NoneType to omit labels entirely.

    """
    self.entry = gdata_entry
    self.intra_property_delimiter = intra_property_delimiter
    self.label_delimiter = label_delimiter

  @property
  def title(self):
    """Title or name."""
    return self.entry.title.text
  name = title

  @property
  def url(self):
    """url_direct or url_site, depending on url_style defined in config."""
    return self._url(googlecl.get_config_option('GENERAL', 'url_style'))

  @property
  def url_direct(self):
    """Url that leads directly to content."""
    return self._url('direct')

  @property
  def url_site(self):
    """Url that leads to site hosting content."""
    return self._url('site')

  def _url(self, substyle):
    if not self.entry.GetHtmlLink():
      href = ''
    else:
      href = self.entry.GetHtmlLink().href

    if substyle == 'direct':
      return entry.content.src or href
    return href or self.entry.content.src

  @property
  def summary(self):
    """Summary or description."""
    try:
      # Try to access the "default" description
      return entry.media.description.text
    except AttributeError:
      # If it's not there, try the summary attribute
      return entry.summary.text
    else:
      if not value:
        # If the "default" description was there, but it was empty,
        # try the summary attribute.
        return entry.summary.text
  description = summary

  @property
  def tags(self):
    """Tags / keywords or labels."""
    try:
      return entry.media.description.keywords.text
    except AttributeError:
      # Blogger uses categories.
      return join_string.join([c.term for c in entry.category if c.term])
  labels = tags
  keywords = tags

  @property
  def xml(self):
    """Raw XML."""
    return str(entry)

  def _extract_label(self, entry_list_item, backup_attr=None):
    """Determine the human-readable label of the item."""
    if hasattr(entry_list_item, 'rel'):
      scheme_or_label = entry_list_item.rel
    elif hasattr(entry_list_item, 'label'):
      scheme_or_label = entry_list_item.label
    elif backup_attr and hasattr(entry_list_item, backup_attr):
      scheme_or_label = getattr(entry_list_item, backup_attr)
    else:
      return None

    if scheme_or_label:
      return scheme_or_label[scheme_or_label.find('#')+1:]
    else:
      return None

  def _join(self, entry_list, text_attribute='text',
            text_extractor=None, label_attribute=None):
    """Join a list of entries into a string.

    Keyword arguments:
      entry_list: List of entries to be joined.
      text_attribute: String of the attribute that will give human readable
                      text for each entry in entry_list. Default 'text'.
      text_extractor: Function that can be used to get desired text.
                      Default None. Use this if the readable data is buried
                      deeper than a single attribute.
      label_attribute: If the attribute for the label is not 'rel' or 'label'
                       it can be specified here.

    Returns:
      String from joining the items in entry_list.

    """
    if not text_extractor:
      if not text_attribute:
        raise Error('One of "text_extractor" or ' +
                    '"text_attribute" must be defined!')
      text_extractor = lambda entry: getattr(entry, text_attribute)

    if self.label_delimiter is None:
      return self.intra_property_delimiter.join([text_extractor(e)
                                                 for e in entry_list
                                                 if text_extractor(e)])
    else:
      separating_string = self.intra_property_delimiter + ' '
      joined_string = ''
      for entry in entry_list:
        if self.label_delimiter is not None:
          label = self._extract_label(entry, backup_attr=label_attribute)
          if label:
            joined_string += label + self.label_delimiter
        joined_string += text_extractor(entry) + separating_string
      return joined_string.rstrip(separating_string)


def compile_entry_string(entry, attribute_list, delimiter,
                         missing_field_value=None):
  """Return a useful string describing a gdata.data.GDEntry.
  
  Keyword arguments:
    wrapped_entry: BaseEntryToStringWrapper to display.
    attribute_list: List of attributes to access
    delimiter: String to use as the delimiter between attributes.
    missing_field_value: If any of the styles for any of the entries are
                         invalid or undefined, put this in its place
                         (Default None to use "missing_field_value" config
                         option).
  
  """

  return_string = ''
  missing_field_value = missing_field_value or googlecl.CONFIG.get('GENERAL',
                                                          'missing_field_value')
  if not delimiter:
    delimiter = ','
  if delimiter.strip() == ',':
    entry.intra_property_delimiter = ';'
  else:
    entry.intra_property_delimiter = ','
  entry.label_delimiter = None
  for attr in attribute_list:
    try:
      # Get the value, replacing NoneTypes and empty strings
      # with the missing field value.
      val = getattr(entry, attr) or missing_field_value
    except ValueError, err:
      print err.args[0] + ' (Did not add value for style ' + attr + ')'
    except AttributeError, err:
      val = missing_field_value
    # Ensure the delimiter won't appear in a non-delineation role,
    # but let it slide if the raw xml is being dumped
    if attr != 'xml':
      return_string += val.replace(delimiter, ' ') + delimiter
    else:
      return_string = val
  
  return return_string.rstrip(delimiter)


def generate_tag_sets(tags):
  """Generate sets of tags based on a string.
  
  Keyword arguments:
    tags: Comma-separated list of tags. Tags with a '-' in front will be
          removed from each photo. A tag of '--' will delete all tags.
          A backslash in front of a '-' will keep the '-' in the tag.
          Examples:
            'tag1, tag2, tag3'      Add tag1, tag2, and tag3
            '-tag1, tag4, \-tag5'   Remove tag1, add tag4 and -tag5
            '--, tag6'              Remove all tags, then add tag6
  Returns:
    (remove_set, add_set, replace_tags) where...
      remove_set: set object of the tags to remove
      add_set: set object of the tags to add
      replace_tags: boolean indicating if all the old tags are removed
      
  """
  tags = tags.replace(', ', ',')
  tagset = set(tags.split(','))
  remove_set = set(tag[1:] for tag in tagset if tag[0] == '-')
  if '-' in remove_set:
    replace_tags = True
  else:
    replace_tags = False
  add_set = set()
  if len(remove_set) != len(tagset):
    # TODO: Can do this more cleanly with regular expressions?
    for tag in tagset:
      # Remove the escape '\' for calculation of 'add' set
      if tag[:1] == '\-':
        add_set.add(tag[1:])
      # Don't add the tags that are being removed
      elif tag[0] != '-':
        add_set.add(tag) 
  return (remove_set, add_set, replace_tags)
