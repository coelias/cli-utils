#!python
import boto3
from datetime import datetime, timedelta
import time
import rlcompleter
import readline
import re
from dateutil import parser
import sys
import json
import uuid
import os
import code

readline.parse_and_bind ("bind ^I rl_complete")
readline.set_completer_delims(' \t')


class CloudWatchCLI():
    def __init__(self):
        self.CMDS = {i[4:]:getattr(self,i) for i in dir(self) if i.startswith('CMD_')}
        self.COMPLETERS = {i[10:]:getattr(self,i) for i in dir(self) if i.startswith('COMPLETER_')}
        self.matches=[None]

        self.ENVS=['sandbox','prod','staging']

        self.VARS={"env":None, "log_group": None}
        self.last=None

    def cmdloop(self):
        while True:
            readline.set_completer(self.main_completer)
            try:
                self.process_command(input("cloudWatch> "))
            except EOFError as e:
                break

    def main_completer(self,text,state):
        if state==0:
            if re.match("^\S*$",readline.get_line_buffer()):
                self.matches=[i+" " for i in self.CMDS if i.startswith(text)] + [None]
            elif re.match("^\S+\s+\S*$",readline.get_line_buffer()):
                cmd=re.findall("^(\S+)\s",readline.get_line_buffer())
                if not cmd: self.matches=[None]
                elif cmd[0] in self.COMPLETERS:
                    self.matches=[(i,i[i.find(text):]) for i in self.COMPLETERS[cmd[0]]() if text in i]
                    if len(self.matches)>1:
                        self.matches = [i[1] for i in self.matches]+[None]
                    elif len(self.matches)==1:
                        self.matches=[self.matches[0][0]+" ",None]
                    else:
                        self.matches=[None]

            elif re.match("^\S+\s+\S+\s+",readline.get_line_buffer()):
                self.matches=[None]

        return self.matches[state]

    def process_command(self,cmd):
        parsed = re.findall('^(?:\s*(\S+))?(?:\s+(\S+.*))?$',cmd.strip())
        if not parsed or not parsed[0][0]:
            return

        cmd,arg = parsed[0]

        if cmd not in self.CMDS:
            print(f'Command "{cmd}" does not exist')
        else:
            try:
                self.CMDS[cmd](*re.findall('\S+',arg))
            except Exception as ex:
                print (f'Error: {ex}')
                
    def COMPLETER_profile(self):
        return self.ENVS

    def CMD_profile(self, profile):
        assert profile in self.ENVS, f'Environment "{profile}" is not a valid one'
        self.VARS['env']=profile
        boto3.setup_default_session(profile_name=profile)
        self.client = boto3.client('logs')

    def get_log_groups(self):
        try:
            data=a=self.client.describe_log_groups()
            lg = []
            while "nextToken" in a:
                lg.extend(i['logGroupName'] for i in a['logGroups'])
                a=self.client.describe_log_groups(nextToken=a['nextToken'])
                data['logGroups'].extend(a['logGroups'])
            lg.extend(i['logGroupName'] for i in a['logGroups'])
            self.last=data
        except Exception as e:
            print(f'ERROR: {e}')

        return lg

    def COMPLETER_log(self):
        return self.get_log_groups()

    def CMD_log(self, log_group):
        assert log_group in self.get_log_groups(), f'Log group "{log_group}" is not a valid one'
        self.VARS['log_group'] = log_group

    def CMD_querylog(self,start_time,end_time,*query):
        assert self.VARS['log_group'],'No log group has been selected'

        start_time=int(parser.parse(start_time,dayfirst=True).timestamp())
        end_time=int(parser.parse(end_time,dayfirst=True).timestamp())

        delta=86400

        results=[]
        while start_time<end_time:
            r = self.fetch_results(start_time,min(start_time+delta,end_time)," ".join(query))
            if len(r)==10000:
                delta=int(delta*.75)
            else:
                sys.stderr.write(f'Time left: {(end_time-start_time)}\n')
                start_time+=delta
                results.extend(list(r))

        for i in results:
            try:
                i[1]['value']=json.loads(i[1]['value'])
            except:
                pass

        self.last=results
        sys.stderr.write(f'Records fetched: {len(list(results))}\n')

    def CMD_interact(self):
        from  pprint import pprint as pp
        last=self.last
        code.interact(local=locals(),banner = '\nVariable "last" contains the last fetched data, print it with "pp(last)"\nYou can start typing python\n')

    def CMD_store(self,*args):
        if not args:
            path = f'/tmp/{str(uuid.uuid4())[:8]}.json'
        else:
            path = args[0]

        if os.path.exists(path):
            sys.stderr.write(f'File "{path}" exists, aborting!\n')
            return

        with open(path,"w") as f:
            f.write(json.dumps(self.last,indent=4))

        sys.stderr.write(f'Output written into "{path}"\n')

    def fetch_results(self,start_time, end_time, query):
         response = self.client.start_query(
             logGroupName=self.VARS['log_group'],
             startTime=start_time,
             endTime=end_time,
             queryString=query,
             limit=10000
         )
         query_id = response['queryId']

         response=None
         while response == None or response['status'] == 'Running':
             time.sleep(1)
             response = self.client.get_query_results(
                 queryId=query_id
             )

         return response['results']

CloudWatchCLI().cmdloop()
