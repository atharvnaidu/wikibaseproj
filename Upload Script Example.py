#Script to import all frames, roles, and LU's from csv dump of webtool sql database to wikibase project
#It seems to take 2-3 hours for this import to finish. It checks for preexisting items, so it can be restarted/continued over multiple sessions.

from wikibaseintegrator.wbi_config import config as wbi_config
from wikibaseintegrator import wbi_login, datatypes, WikibaseIntegrator
from wikibaseintegrator.models import Reference, References, Form, Sense
from wikibaseintegrator.models.qualifiers import Qualifiers
from wikibaseintegrator.models.claims import Claim
from wikibaseintegrator.wbi_enums import ActionIfExists
import logging
import csv
import json
import pandas as pd
import requests
import sys,time
from datetime import datetime
import re



# sparqler, a class for make SPARQL queries to the Wikidata Query Service and other endpoints.
version = '1.1'
created = '2023-02-12'

# (c) 2022-2023 Steven J. Baskauf
# This program is released under a GNU General Public License v3.0 http://www.gnu.org/licenses/gpl-3.0
# Author: Steve Baskauf

# -----------------------------------------
# Version 1.0 change notes (2022-06-07):
# - Initial version
# -----------------------------------------
# Version 1.1 change notes (2023-02-12):
# - Added support for sessions
# -----------------------------------------


import datetime
import time
import json

class Sparqler:
    """Build SPARQL queries of various sorts

    Parameters
    -----------
    method: str
        Possible values are "post" (default) or "get". Use "get" if read-only query endpoint.
        Must be "post" for update endpoint.
    endpoint: URL
        Defaults to Wikidata Query Service if not provided.
    useragent : str
        Required if using the Wikidata Query Service, otherwise optional.
        Use the form: appname/v.v (URL; mailto:email@domain.com)
        See https://meta.wikimedia.org/wiki/User-Agent_policy
    session: requests.Session
        If provided, the session will be used for all queries. Note: required for the Commons Query Service.
        If not provided, a generic requests method (get or post) will be used.
        NOTE: Currently only implemented for the .query() method since I don't have any way to test the mehtods that write.
    sleep: float
        Number of seconds to wait between queries. Defaults to 0.1
        
    Required modules:
    -------------
    requests, datetime, time
    """
    def __init__(self, method='post', endpoint='https://query.wikidata.org/sparql', useragent=None, session=None, sleep=0.1):
        # attributes for all methods
        self.http_method = method
        self.endpoint = endpoint
        if useragent is None:
            if self.endpoint == 'https://query.wikidata.org/sparql':
                print('You must provide a value for the useragent argument when using the Wikidata Query Service.')
                print()
                raise KeyboardInterrupt # Use keyboard interrupt instead of sys.exit() because it works in Jupyter notebooks
        self.session = session
        self.sleep = sleep

        self.requestheader = {}
        if useragent:
            self.requestheader['User-Agent'] = useragent
        
        if self.http_method == 'post':
            self.requestheader['Content-Type'] = 'application/x-www-form-urlencoded'

    def query(self, query_string, form='select', verbose=False, **kwargs):
        """Sends a SPARQL query to the endpoint.
        
        Parameters
        ----------
        form : str
            The SPARQL query form.
            Possible values are: "select" (default), "ask", "construct", and "describe".
        mediatype: str
            The response media type (MIME type) of the query results.
            Some possible values for "select" and "ask" are: "application/sparql-results+json" (default) and "application/sparql-results+xml".
            Some possible values for "construct" and "describe" are: "text/turtle" (default) and "application/rdf+xml".
            See https://docs.aws.amazon.com/neptune/latest/userguide/sparql-media-type-support.html#sparql-serialization-formats-neptune-output
            for response serializations supported by Neptune.
        verbose: bool
            Prints status when True. Defaults to False.
        default: list of str
            The graphs to be merged to form the default graph. List items must be URIs in string form.
            If omitted, no graphs will be specified and default graph composition will be controlled by FROM clauses
            in the query itself. 
            See https://www.w3.org/TR/sparql11-query/#namedGraphs and https://www.w3.org/TR/sparql11-protocol/#dataset
            for details.
        named: list of str
            Graphs that may be specified by IRI in a query. List items must be URIs in string form.
            If omitted, named graphs will be specified by FROM NAMED clauses in the query itself.
            
        Returns
        -------
        If the form is "select" and mediatype is "application/json", a list of dictionaries containing the data.
        If the form is "ask" and mediatype is "application/json", a boolean is returned.
        If the mediatype is "application/json" and an error occurs, None is returned.
        For other forms and mediatypes, the raw output is returned.

        Notes
        -----
        To get UTF-8 text in the SPARQL queries to work properly, send URL-encoded text rather than raw text.
        That is done automatically by the requests module for GET. I guess it also does it for POST when the
        data are sent as a dict with the urlencoded header. 
        See SPARQL 1.1 protocol notes at https://www.w3.org/TR/sparql11-protocol/#query-operation        
        """
        query_form = form
        if 'mediatype' in kwargs:
            media_type = kwargs['mediatype']
        else:
            if query_form == 'construct' or query_form == 'describe':
            #if query_form == 'construct':
                media_type = 'text/turtle'
            else:
                media_type = 'application/sparql-results+json' # default for SELECT and ASK query forms
        self.requestheader['Accept'] = media_type
            
        #create frames with frame query 
        #use merged df and add lus for frames after checking they don't already exist
        payload = {'query' : query_string}
        if 'default' in kwargs:
            payload['default-graph-uri'] = kwargs['default']
        
        if 'named' in kwargs:
            payload['named-graph-uri'] = kwargs['named']

        if verbose:
            print('querying SPARQL endpoint')

        start_time = datetime.datetime.now()
        if self.http_method == 'post':
            if self.session is None:
                response = requests.post(self.endpoint, data=payload, headers=self.requestheader)
            else:
                response = self.session.post(self.endpoint, data=payload, headers=self.requestheader)
        else:
            if self.session is None:
                response = requests.get(self.endpoint, params=payload, headers=self.requestheader)
            else:
                response = self.session.get(self.endpoint, params=payload, headers=self.requestheader)
        elapsed_time = (datetime.datetime.now() - start_time).total_seconds()
        self.response = response.text
        time.sleep(self.sleep) # Throttle as a courtesy to avoid hitting the endpoint too fast.

        if verbose:
            print('done retrieving data in', int(elapsed_time), 's')

        if query_form == 'construct' or query_form == 'describe':
            return response.text
        else:
            if media_type != 'application/sparql-results+json':
                return response.text
            else:
                try:
                    data = response.json()
                except:
                    return None # Returns no value if an error. 

                if query_form == 'select':
                    # Extract the values from the response JSON
                    results = data['results']['bindings']
                else:
                    results = data['boolean'] # True or False result from ASK query 
                return results           

    def update(self, request_string, mediatype='application/json', verbose=False, **kwargs):
        """Sends a SPARQL update to the endpoint.
        
        Parameters
        ----------
        mediatype : str
            The response media type (MIME type) from the endpoint after the update.
            Default is "application/json"; probably no need to use anything different.
        verbose: bool
            Prints status when True. Defaults to False.
        default: list of str
            The graphs to be merged to form the default graph. List items must be URIs in string form.
            If omitted, no graphs will be specified and default graph composition will be controlled by USING
            clauses in the query itself. 
            See https://www.w3.org/TR/sparql11-update/#deleteInsert
            and https://www.w3.org/TR/sparql11-protocol/#update-operation for details.
        named: list of str
            Graphs that may be specified by IRI in the graph pattern. List items must be URIs in string form.
            If omitted, named graphs will be specified by USING NAMED clauses in the query itself.
        """
        media_type = mediatype
        self.requestheader['Accept'] = media_type
        
        # Build the payload dictionary (update request and graph data) to be sent to the endpoint
        payload = {'update' : request_string}
        if 'default' in kwargs:
            payload['using-graph-uri'] = kwargs['default']
        
        if 'named' in kwargs:
            payload['using-named-graph-uri'] = kwargs['named']

        if verbose:
            print('beginning update')
            
        start_time = datetime.datetime.now()
        response = requests.post(self.endpoint, data=payload, headers=self.requestheader)
        elapsed_time = (datetime.datetime.now() - start_time).total_seconds()
        self.response = response.text
        time.sleep(self.sleep) # Throttle as a courtesy to avoid hitting the endpoint too fast.

        if verbose:
            print('done updating data in', int(elapsed_time), 's')

        if media_type != 'application/json':
            return response.text
        else:
            try:
                data = response.json()
            except:
                return None # Returns no value if an error converting to JSON (e.g. plain text) 
            return data           

    def load(self, file_location, graph_uri, s3='', verbose=False, **kwargs):
        """Loads an RDF document into a specified graph.
        
        Parameters
        ----------
        s3 : str
            Name of an AWS S3 bucket containing the file. Omit load a generic URL.
        verbose: bool
            Prints status when True. Defaults to False.
        
        Notes
        -----
        The triplestore may or may not rely on receiving a correct Content-Type header with the file to
        determine the type of serialization. Blazegraph requires it, AWS Neptune does not and apparently
        interprets serialization based on the file extension.
        """
        if s3:
            request_string = 'LOAD <https://' + s3 + '.s3.amazonaws.com/' + file_location + '> INTO GRAPH <' + graph_uri + '>'
        else:
            request_string = 'LOAD <' + file_location + '> INTO GRAPH <' + graph_uri + '>'
        
        if verbose:
            print('Loading file:', file_location, ' into graph: ', graph_uri)
        data = self.update(request_string, verbose=verbose)
        return data

    def drop(self, graph_uri, verbose=False, **kwargs):
        """Drop a specified graph.
        
        Parameters
        ----------
        verbose: bool
            Prints status when True. Defaults to False.
        """
        request_string = 'DROP GRAPH <' + graph_uri + '>'

        if verbose:
            print('Deleting graph:', graph_uri)
        data = self.update(request_string, verbose=verbose)
        return data



basic_items_filename = "basic_items.json"
basic_properties_filename = "basic_properties.json"
login_info_filename = "login_info.json"

basic_items_file = open(basic_items_filename,'r')
basic_properties_file = open(basic_properties_filename,'r')
login_info_file = open(login_info_filename,'r')

basic_items = json.load(basic_items_file)
basic_properties = json.load(basic_properties_file)
login_info = json.load(login_info_file)


#Set this string to the wiki url base
wiki_url = f'{login_info["wiki_url"]}'

wbi_config["WIKIBASE_URL"] = f'{wiki_url}'
wbi_config["MEDIAWIKI_INDEX_URL"] = f'{wiki_url}/w/index.php'

wbi_config["MEDIAWIKI_API_URL"] = f'{wiki_url}/w/api.php'
wbi_config["MEDIAWIKI_REST_URL"] = f'{wiki_url}/w/rest.php'

login_instance = wbi_login.OAuth1(consumer_token=f'{login_info["consumer_token"]}', consumer_secret=f'{login_info["consumer_secret"]}',access_token=f'{login_info["access_token"]}',access_secret=f'{login_info["access_secret"]}')




wbi = WikibaseIntegrator(login=login_instance)

endpoint_url = f'{wiki_url}/query/sparql'
wbwh = Sparqler(endpoint=endpoint_url)

#query for frames 
properNounQuery = f"""
PREFIX pr: <{wiki_url}/prop/direct/> #prefix for properties
PREFIX it: <{wiki_url}/entity/> #prefix for Q-items and L-items

SELECT ?lex ?lemma WHERE {{
  ?lex a ontolex:LexicalEntry ;
         wikibase:lexicalCategory it:Q53 ; #Q53 = proper noun
         wikibase:lemma ?lemma .
}}
"""


properNounQueryResults = wbwh.query(properNounQuery)

#print(properNounQueryResults[-1]['lemma'])
#print(properNounQueryResults[-1]['lemma']['value'])

df = pd.read_csv('CIGS v1.5 Nov 30 2022.csv')
AncientNamesColumn = df['anc_name'].values

setOfProperNouns = set()


for val in properNounQueryResults:
    setOfProperNouns.add(val['lemma']['value'])

matching_entries = {}

for index, row in df.iterrows():
    anc_name = row['anc_name'] 
    mod_name = row['transc_name']
    print(anc_name)
    if (pd.notna(anc_name) and anc_name.lower() in setOfProperNouns):
        # Add the matching entry and its features to the dictionary
        matching_entries[anc_name] = row.to_dict()
    elif (pd.notna(mod_name) and mod_name.lower() in setOfProperNouns):
        matching_entries[mod_name] = row.to_dict()

# Print the dictionary containing the matching entries
print(matching_entries)

with open('matching_entries.json', 'w') as json_file:
    json.dump(matching_entries, json_file, indent=4)