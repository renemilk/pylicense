#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# pylicense (https://github.com/ftalbrecht/pylicense): addheader.py
# Copyright Holders: Felix Albrecht
# License: BSD 2-Clause License (http://opensource.org/licenses/BSD-2-Clause)

"""
Add header to a given file.

Usage:
    addheader.py [-hv] [--help] [--verbose] --cfg=CONFIG_FILE PATH


Arguments:
    PATH            Directory or file to process.

Options:
    -h, --help      Show this message.

    -v, --verbose   Be verbose.
"""


from __future__ import print_function
import ConfigParser
from docopt import docopt
from collections import defaultdict
import subprocess
import os
import sys
import re
import fnmatch


class ConfigError(Exception):
    pass


class GitError(Exception):
    pass


def process_dir(dirname, config):
    if os.path.isfile(dirname):
        yield (dirname, '')
    elif os.path.isdir(dirname):
        include = re.compile('|'.join(fnmatch.translate(p) for p in config.get('files', 'include_patterns').split()))
        exclude = re.compile('|'.join(fnmatch.translate(p) for p in config.get('files', 'exclude_patterns').split()))
        os.chdir(dirname)
        for root, _, files in os.walk(dirname):
            for abspath in sorted([os.path.join(root, f) for f in files]):
                if include.match(abspath) and not exclude.match(abspath) and not os.path.islink(abspath):
                    yield (abspath, dirname)
    else:
        raise Exception


def process_file(filename, config, root):
    # parse config
    assert(config.has_option('header', 'name'))
    project_name = config.get('header', 'name').strip()
    assert(config.has_option('header', 'license'))
    license = config.get('header', 'license').strip()
    url = config.get('header', 'url').strip() if config.has_option('header', 'url') else None
    copyright_statement = (config.get('header', 'copyright_statement').strip()
                           if config.has_option('header', 'copyright_statement')
                           else 'The copyright lies with the authors of this file (see below).')
    max_width = int(config.get('header', 'max_width')) if config.has_option('header', 'max_width') else 78
    prefix = config.get('header', 'prefix') if config.has_option('header', 'prefix') else '#'
    # read authors and respective years
    authors = {}
    try:
        ret = subprocess.Popen('git log --use-mailmap --follow --pretty=format:"%aN %ad" --date=format:%Y {} | sort | uniq'.format(filename),
                                shell=True,
                                cwd=root,
                                stdout=subprocess.PIPE,
                                stderr=sys.stderr)
        out, _ = ret.communicate()
        git_info = sorted(out.splitlines())
        years_per_author = defaultdict(set)
        for year_and_author in git_info:
            year_and_author = year_and_author.strip().split(' ')
            assert len(year_and_author) > 1 # otherwise we have either no name or no year
            author = ' '.join([word.decode('utf8') for word in year_and_author[:-1]]).replace(u'é', 'e')
            years_per_author[author].add(int(year_and_author[-1]))
        # parse years
        for author, years in years_per_author.items():
            years = sorted(years)
            assert len(years) > 0
            year_ranges = []
            start_year = years[0]
            end_year = -1
            for ii in range(1, len(years)):
                current_year = years[ii]
                if current_year == years[ii - 1] + 1:
                    end_year = current_year
                else: # current_year > years[ii - 1], since these are sorted
                    year_ranges.append((start_year, end_year) if end_year > start_year else start_year)
                    end_year = -1
                    start_year = current_year
            if end_year > start_year:
                year_ranges.append((start_year, end_year))
            elif len(year_ranges) == 0 or start_year != years[0]:
                year_ranges.append(start_year)

            def years_to_string(year_range):
                if isinstance(year_range, tuple):
                    assert len(year_range) == 2
                    return '{} - {}'.format(year_range[0], year_range[1])
                else:
                    return '{}'.format(year_range)

            assert len(year_ranges)
            authors[author] = years_to_string(year_ranges[0])
            for ii in range(1, len(year_ranges)):
                authors[author] += ', ' + years_to_string(year_ranges[ii])
    except:
        raise GitError('failed to extract authors from git history!')

    def write_header(target, header):
        shebang, encoding = header['shebang'], header['encoding']
        if shebang:
            target.write(shebang + '\n')
        if encoding:
            target.write(prefix + ' ' + encoding + '\n')
        if shebang or encoding:
            target.write(prefix + '\n')
        # project name and url
        line = prefix + ' ' + project_name
        if url is not None:
            if len(line) + len(url) + len('().') <= max_width:
                target.write(u'{line} ({url}).\n'.format(line=line, url=url))
            else:
                target.write(line + '\n')
                if max_width - len(prefix) - 1 - len(url):
                    target.write(u'{prefix}   {url}\n'.format(prefix=prefix, url=url))
                else:
                    target.write(u'{prefix} {url}\n'.format(prefix=prefix, url=url))
        # copyright statement
        target.write(prefix + ' ' + copyright_statement + '\n')
        # license
        target.write(u'{p} License: {l}\n'.format(p=prefix, l=license))
        # authors
        target.write(prefix + ' Authors:\n')
        max_author_length = 0
        for author in authors:
            max_author_length = max(max_author_length, len(author))
        for author in sorted(authors.keys()):
            year = '(' + authors[author] + ')'
            if len(prefix) + 4 + max_author_length + len(year) <= max_width:
                for ii in range(max_author_length - len(author)):
                    author += ' '
            target.write((u'{}   {} {}\n'.format(prefix, author, year)).encode('utf8'))
        # comments
        def prune_first_empty_comments(ll):
            first_real_comment_line = False
            ret = []
            for line in ll:
                line = line.strip()
                if first_real_comment_line:
                    ret.append(line)
                elif len(line) >= len(line) and len(line[len(prefix):].strip()) > 0:
                    first_real_comment_line = True
                    ret.append(line)
            return ret
        comments = header['comments']
        if comments and len(comments) > 0:
            comments.reverse()
            comments = prune_first_empty_comments(comments)
            comments.reverse()
            comments = prune_first_empty_comments(comments)
            if len(comments) > 0:
                target.write(prefix + '\n')
            for comment in comments:
                target.write(comment + '\n')

    source = open(filename).readlines()
    source.append(None)
    source_iter = iter(source)

    warning = ''

    # read existing header
    header = {'shebang': None,
              'encoding': None,
              'comments': []}
    could_be_an_author = False
    while True:
        line = next(source_iter)
        if line is None:
            break
        dirt_to_remove = ['\xef', '\xbb', '\xbf']
        while len(line) > 0 and line[0] in dirt_to_remove:
            for dirt in dirt_to_remove:
                line = line.lstrip(dirt)
        if len(line) == 0:
            break
        if line.startswith('#!') and len(line.strip()) > 2:
            header['shebang'] = line.strip()
            continue
        if not line.startswith(prefix):
            break
        else:
            can_be_discarded = ['Copyright', 'copyright', 'License']
            for ii in (project_name, copyright_statement, license):
                for ll in ii.split('\n'):
                    can_be_discarded.append(ll.strip().lstrip(prefix).strip())
            if re.match('.*coding[:=]\s*', line):
                header['encoding'] = line[len(prefix):]
            elif any([line[len(prefix):].strip().startswith(discard) for discard in can_be_discarded]):
                continue
            elif line[len(prefix):].strip().startswith(url):
                continue
            elif any([line[len(prefix):].strip().startswith(some_url) for some_url in ('http://', 'https://')]):
                warning = 'dropping url \'{}\'!'.format(line[len(prefix):].strip())
            elif line[len(prefix):].strip().startswith('Authors:'): # the following header lines may be authors
                could_be_an_author = True
                continue
            elif could_be_an_author:
                if line[len(prefix):].startswith('  ') and line.strip()[-1] == ')': # we just have to assume that this is an author line
                    continue
                else:
                    could_be_an_author = False
                    # from now on this is a comment
                    header['comments'].append(line)
            else:
                header['comments'].append(line)

    # write new file
    with open(filename, 'w') as target:

        # skip lines containing only whitespace
        while line is not None and line.isspace():
            line = next(source_iter)

        write_header(target, header)
        target.write('\n')

        # copy all remaining content
        while line is not None:
            target.write(line)
            line = next(source_iter)

    return warning

if __name__ == '__main__':
    # parse arguments
    args = docopt(__doc__)
    verbose = False
    if args['--verbose']:
        verbose = True
    config = ConfigParser.SafeConfigParser()
    if args['--cfg'] is not None:
        config.readfp(open(args['--cfg']))
    else:
        raise ConfigError('No suitable config file given (try \'--cfg CONFIG_FILE\')!')
    for filename, dirname in process_dir(args['PATH'], config):
        print('{}: '.format(filename[(len(dirname)):]), end='')
        try:
            res = process_file(filename, config, dirname if dirname != '' else '.')
            print('{}'.format(res if len(res) else 'success'))
        except GitError as e:
            print(e)
