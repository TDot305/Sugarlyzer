import sys
import os
import shutil
import json
import re
from html.parser import HTMLParser


class HTMLAtomizer(HTMLParser):
  def __init__(self):
    self.state = 'empty'
    self.curln = '0'
    self.msgType = ''
    self.location = ''
    self.msg = ''
    self.lines = []
    self.asserts = []
    super().__init__()

  def handle_starttag(self, tag, attrs):
    if tag == 'h3':
      self.state = 'inHeader'
    if tag == 'td' and len(attrs) == 1 and attrs[0][0] == 'class' and self.state == 'inBugSummary1':
      self.state = 'inBugSummary2'
    elif tag == 'td' and len(attrs) == 1 and attrs[0][0] == 'class' and self.state == 'inBugSummary2':
      self.state = 'inBugSummary3'
    if self.state == 'inBugSummary4' and tag == 'a' and len(attrs) == 1 and attrs[0][1] == '#EndPath':
      self.state = 'inBugSummary5'
    if tag == 'table' and len(attrs) == 2 and attrs[0][1] == 'code':
      self.state = 'incode'
    if tag == 'tr' and (self.state == 'incode' or self.state == 'inline' or self.state == 'inpath') and len(attrs) == 2 and attrs[0][1] == 'codeline':
      self.curln = attrs[1][1]
      self.state = 'inline'
    if tag == 'div' and self.state == 'inline' and len(attrs) > 0 and 'Path' in attrs[0][1]:
      self.state = 'inpath'
      self.lines.append(self.curln)

    
  def handle_endtag(self, tag):
    if self.state == 'inBugSummary6' and tag == 'br':
      self.state = 'inBugSummary7'

  def handle_data(self, data):
    if self.state == 'inHeader':
      if data == 'Bug Summary':
        self.state = 'inBugSummary1'
    if self.state == 'inBugSummary3':
      self.msgType = data
      self.state = 'inBugSummary4'
    if self.state == 'inBugSummary5':
      self.location = data
      self.state = 'inBugSummary6'
    if self.state == 'inBugSummary7':
      self.state = 'empty'
      self.msg = data
    if self.state == 'inpath' and 'Assuming' in data and 'static_condition_default' in data:
      self.state = 'incode'
      asrt = {}
      asrt['var'] = data.split("'")[1]
      if 'not' in data.split("'")[2] or 'true' in data.split("'")[2]:
        asrt['val'] = True
      else:
        asrt['val'] = False
      self.asserts.append(asrt)
        
def atomize(reportFile):
  rf = open(reportFile,'r')
  parser = HTMLAtomizer()
  parser.feed(rf.read())
  ret = {}
  ret['msg'] = parser.msg
  ret['msgtype'] = parser.msgType
  ret['loc'] = parser.location
  ret['lines'] = parser.lines
  '''
  Separate the asserts to be a list of if locations and
  assumptions, we parse this out automatically ourselves.
  '''
  ret['asserts'] = parser.asserts
  return ret

if __name__ == '__main__':
  atomize(sys.argv[1]) #report
