#! python
"""
Simple example script for running and testing IPython notebooks.

usage: ipynbtest.py [-h] [--timeout TIMEOUT] [--rerun-if-timeout [RERUN]]
                    [--restart-if-fail [RESTART]] [--strict] [--eval [EVAL]]
                    [--pass-if-timeout] [--show-diff] [--abort-if-fail]
                    [--verbose]
                    file.ipynb

Run all cells in an ipython notebook as a test and check whether these
successfully execute and compares their output to the one inside the notebook

positional arguments:
  file.ipynb            the notebook to be checked

optional arguments:
  -h, --help            show this help message and exit
  --timeout TIMEOUT     the default timeout time in seconds for a cell
                        evaluation. Default is 300s (5mins). Note that travis
                        will consider it an error by default if after 600s
                        (10mins) no output is generated. So 600s is the
                        default limit by travis. However, a test cell that
                        takes this long should be split in more than one or
                        simplified.
  --rerun-if-timeout [RERUN]
                        if set then a timeout in a cell will cause to run the.
                        Default is 2 (means make up to 3 attempts)
  --restart-if-fail [RESTART]
                        if set then a fail in a cell will cause to restart the
                        full notebook!. Default is 0 (means NO rerun).Use this
                        with care.
  --strict              if set to true then the default test is that cell have
                        to match otherwise a diff will not be considered a
                        failed test
  --eval [EVAL]         the argument will be run before the first cell is
                        executed. This can be used to set specific values
                        without changing the notebook.
  --pass-if-timeout     if set then a timeout (after last retry) is considered
                        a passed test
  --show-diff           if set to true differences in the cell are shown in
                        `diff` style
  --abort-if-fail       if set to true then a fail will stop the whole test.
  --verbose             if set then text output is send to the console.


Each cell is submitted to the kernel, and the outputs are compared with those
stored in the notebook.

This version needs IPython 3.0.0 and makes use of some nice features. It can
handle notebooks of version 3 (IPython 2) and version 4 (IPython 3).

CHANGELOG
---------
Oct-05 2015:
- Added support for IPython 4.0.0 / Jupyter. This had some extensive
  packages renamed but should work now.
- Reduced the latency for cell to 0.05 seconds. This should be enough on a
  local machine to get the result.

Nov-09 2015:
- Added support for --abort-if-fail and --eval [pythoncommand]
- Moved to separate installable package

May-17 2016:
- Fix creating of stdout cell. Depending on cache flushing multiple output cell
  coult have been generated during running while store files contain only one.
  These will be combined now into one
- Add check for `idle` status to figure out if cell execution is finished.
  This is much faster

Sep-20 2016:
- Removed default --pylab=inline. Added cmd option `extra-arguments` instead
- Little cleanup of the code

The original is found in a gist under https://gist.github.com/minrk/2620735
"""

import os
import sys
import re
import argparse
import uuid
import difflib
import time

from Queue import Empty

try:
    # IPython 4.0.0+ / Jupyter - the big split
    from jupyter_client.manager import KernelManager
    import nbformat

# print 'Found Jupyter / IPython 4+'

except ImportError:
    # IPython 3.0.0+
    from IPython.kernel.manager import KernelManager
    import IPython.nbformat as nbformat


# print 'Using IPython 3+'


class TravisConsole(object):
    """
    A wrapper class to allow easier output to the console especially for travis
    """

    def __init__(self):
        self.stream = sys.stdout
        self.linebreak = '\n'
        self.fold_count = dict()
        self.fold_stack = dict()

        # very complicated, maybe too? complicated
        self.fold_uuid = str(uuid.uuid4()).split('-')[1]

        # check, if we are on travis-ci
        self.travis = os.getenv('TRAVIS', False)

    def fold_open(self, name):
        """
        open the travis fold with given name

        Parameters
        ----------
        name : string
            the name of the fold
        """
        if name not in self.fold_count:
            self.fold_count[name] = 0
            self.fold_stack[name] = []

        self.fold_count[name] += 1
        fold_name = self.fold_uuid + '.' + name.lower() + '.' + str(self.fold_count[name])

        self.fold_stack[name].append(fold_name)

        if self.travis:
            self.writeln("travis_fold:start:" + fold_name)

    def fold_close(self, name):
        """
        close the travis fold with given name

        Parameters
        ----------
        name : string
            the name of the fold
        """
        fold_name = self.fold_uuid + '.' + name.lower() + '.' + str(self.fold_count[name])

        if self.travis:
            self.writeln("travis_fold:end:" + fold_name)

    @staticmethod
    def _indent(s, num=4):
        lines = s.splitlines(True)
        lines = map(lambda x: ' ' * num + x, lines)
        return ''.join(lines)

    def writeln(self, s, indent=0):
        """write a string with linebreak at the end

        Parameters
        ----------
        s : string
            the string to be written to travis console
        indent : int, default 0
            if non-zero add the number of space before each line
        """
        self.write(s, indent)
        if s[-1] != '\n':
            # make a line break if there is none present
            self.br()

    def br(self):
        """
        Write a linebreak
        """
        self.stream.write(self.linebreak)

    def write(self, s, indent=0):
        """write a string to travis output with possible indention

        Parameters
        ----------
        s : string
            the string to be written to travis console
        indent : int, default 0
            if non-zero add the number of space before each line
        """
        if indent > 0:
            self.stream.write(self._indent(s, indent))
        else:
            self.stream.write(s)

        self.stream.flush()

    def warning(self, s):
        self.write(tv.red(s))

    @staticmethod
    def red(s):
        """format a string to be red in travis output

        Parameters
        ----------
        s : string
            string to be colored

        Returns
        -------
        string
            the colored string
        """
        RED = '\033[31m'
        DEFAULT = '\033[39m'
        return RED + s + DEFAULT

    @staticmethod
    def green(s):
        """format a string to be green in travis output

        Parameters
        ----------
        s : string
            string to be colored

        Returns
        -------
        string
            the colored string
        """
        GREEN = '\033[32m'
        DEFAULT = '\033[39m'
        return GREEN + s + DEFAULT

    @staticmethod
    def blue(s):
        """format a string to be blue in travis output

        Parameters
        ----------
        s : string
            string to be colored

        Returns
        -------
        string
            the colored string
        """
        BLUE = '\033[36m'
        DEFAULT = '\033[39m'
        return BLUE + s + DEFAULT

    def format_diff(self, difference):
        """format a list of diff commands for travis output

        this will remove empty lines, lines starting with `?` and
        add coloring depending on whether a line starts with `+` or `-`

        Parameters
        ----------
        difference : list of diff (string)
            the list of diff commands to be formatted

        Returns
        -------
        string
            a string representation of all diffs
        """
        colored_diffs = []
        for line in difference:
            if line[0] == '-':
                colored_diffs.append(self.red(line))
            elif line[0] == '+':
                colored_diffs.append(self.green(line))
            else:
                colored_diffs.append(line)

        # remove unnecessary linebreaks
        colored_diffs = [line.replace('\n', '') for line in colored_diffs]

        # remove line we do not want
        colored_diffs = [line for line in colored_diffs if len(line) > 0 and line[0] != '?']

        return '\n'.join(colored_diffs)


class IPyTestConsole(TravisConsole):
    """
    Add support for different output results
    """

    def __init__(self):
        super(IPyTestConsole, self).__init__()

        self.default_results = {
            'success': True,  # passed without differences
            'kernel': False,  # kernel (IPYTHON) error occurred
            'error': False,  # errors during execution
            'timeout': False,  # kernel run timed out
            'diff': True,  # passed, but with differences in the output
            'skip': True,  # cell has been skipped
            'ignore': True  # cell has been executed, but not compared
        }

        self.pass_count = 0
        self.fail_count = 0
        self.result_count = dict()
        self.last_fail = False

        self.reset()

    def reset(self):
        self.result_count = {key: 0 for key in self.default_results.keys()}
        self.pass_count = 0
        self.fail_count = 0

    def write_result(self, result, okay_list=None):
        """write final result of test

        this keeps track of the result types
        """
        my_list = self.default_results.copy()
        if okay_list is not None:
            my_list.update(okay_list)

        if my_list[result]:
            self.write(self.green('ok'))
            self.pass_count += 1
            self.last_fail = False
        else:
            self.write(self.red('fail'))
            self.fail_count += 1
            self.last_fail = True

        self.writeln(' [' + result + ']')
        self.result_count[result] += 1


class IPyKernel(object):
    """
    A simple wrapper class to run cells in an IPython Notebook.

    Notes
    -----
    - Use `with` construct to properly instantiate
    - IPython 3.0.0+ is assumed for this version

    """

    def __init__(self, nb_version=4, extra_arguments=None):
        # default timeout time is 60 seconds
        self.default_timeout = 60

        if extra_arguments is None:
            extra_arguments = []
        self.extra_arguments = extra_arguments
        self.nb_version = nb_version

    def __enter__(self):
        self.km = KernelManager()
        self.km.start_kernel(
            extra_arguments=self.extra_arguments,
            stderr=open(os.devnull, 'w')
        )

        self.kc = self.km.client()
        self.kc.start_channels()

        self.iopub = self.kc.iopub_channel
        self.shell = self.kc.shell_channel

        # run %pylab inline, because some notebooks assume this
        # even though they shouldn't

        self.shell.send("pass")
        self.shell.get_msg()
        while True:
            try:
                self.iopub.get_msg(timeout=0.05)
            except Empty:
                break

        self.cmd_list = []
        self.msg_list = {}

        return self

    def clear(self):
        self.iopub.get_msgs()

    def execute(self, cmd):
        uid = self.kc.execute(cmd)
        self.cmd_list.append((uid, cmd))
        return uid

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.kc.stop_channels()
        self.km.shutdown_kernel()
        del self.msg_list
        del self.cmd_list
        del self.km

    def listen(self, uid, use_timeout=None):
        if use_timeout is None:
            use_timeout = self.default_timeout

        while True:
            if uid in self.msg_list and len(self.msg_list[uid]) > 0:
                return self.msg_list[uid].pop(0)

            msg = self.iopub.get_msg(timeout=use_timeout)
            if 'msg_id' in msg['parent_header']:
                msg_uid = msg['parent_header']['msg_id']

                if msg_uid not in self.msg_list:
                    self.msg_list[msg_uid] = []

                self.msg_list[msg_uid].append(msg)

    def run(self, cell, use_timeout=None):
        """
        Run a notebook cell in the IPythonKernel

        Parameters
        ----------
        cell : IPython.notebook.Cell
            the cell to be run
        use_timeout : int or None (default)
            the time in seconds after which a cell is stopped and assumed to
            have timed out. If set to None the value in `default_timeout`
            is used

        Returns
        -------
        list of ex_cell_outputs
            a list of NotebookNodes of the returned types. This is
            similar to the list of outputs generated when a cell is run
        """

        if timeout is not None:
            use_timeout = use_timeout
        else:
            use_timeout = self.default_timeout

        if hasattr(cell, 'source'):
            uid = self.execute(cell.source)
        else:
            raise AttributeError('No source/input key')

        outs = []
        stdout_cells = {}

        while True:
            msg = self.listen(uid, use_timeout)

            msg_type = msg['msg_type']

            if msg_type == 'execute_input':
                continue
            elif msg_type == 'clear_output':
                outs = []
                continue
            elif msg_type == 'status':
                if msg['content']['execution_state'] == 'idle':
                    # we are done with the cell, let's compare
                    break

                continue

            out_cell = nbformat.NotebookNode(output_type=msg_type)

            content = msg['content']

            if msg_type == 'stream':
                name = content['name']
                if name not in stdout_cells:
                    out_cell.name = name
                    out_cell.text = content['text']
                    stdout_cells[name] = out_cell
                    outs.append(out_cell)
                else:
                    # we already have a stdout cell, so append to it
                    stdout_cells[name].text += content['text']

            elif msg_type in ('display_data', 'execute_result'):
                if hasattr(content, 'execution_count'):
                    out_cell['execution_count'] = content['execution_count']
                else:
                    out_cell['execution_count'] = None

                out_cell['data'] = content['data']
                out_cell['metadata'] = content['metadata']

                outs.append(out_cell)

            elif msg_type == 'error':
                out_cell.ename = content['ename']
                out_cell.evalue = content['evalue']
                out_cell.traceback = content['traceback']

                outs.append(out_cell)

            elif msg_type.startswith('comm_'):
                # messages used to initialize, close and unpdate widgets
                # we will ignore these and hope for the best
                pass

            else:
                tv.warning("Unhandled iopub msg of type `%s`" % msg_type)

        return outs

    def get_commands(self, cell):
        """
        Extract potential commands from the first line of a cell

        if a code cell starts with the hashbang `#!` it can be followed by
        a comma separated list of commands. Each command can be
        1. a single key `skip`, or
        2. a key/value pair separated by a colon `timeout:[int]`

        Parameters
        ----------
        cell : a NotebookCell
            the cell to be examined

        Returns
        -------
        dict
            a dict of key/value pairs. For a single command the value is `True`
        """
        commands = {}
        source = cell.source
        if source is not None:
            lines = source.splitlines()
            if len(lines) > 0:
                n_line = 0
                line = lines[n_line].strip()
                while line.startswith('#!') or len(line) == 0:
                    txt = line[2:].strip()

                    parts = txt.split(',')
                    for part in parts:
                        subparts = part.split(':')
                        if len(subparts) == 1:
                            commands[subparts[0].strip().lower()] = True
                        elif len(subparts) == 2:
                            commands[subparts[0].strip().lower()] = subparts[1]

                    n_line += 1
                    line = lines[n_line]

        return commands

    def is_empty_cell(self, cell):
        """
        Check if a cell has no code

        Parameters
        ----------
        cell : a NotebookCell
            the cell to be examined

        Returns
        -------
        bool
            True if the cell has no code, False otherwise
        """
        return not bool(cell.source)


class TypedOutput(object):
    """
    Simple class to define possible outputs like stdout, png, etc

    It will know how to detect these, have a name by which to address the
    type and can compare

    """

    name = ''
    output_type = ''

    def __init__(self, output):
        self._out = output
        self._key = None

    def __nonzero__(self):
        return self.otype == self.output_type

    def __eq__(self, other):
        if type(other) is type(self):
            return self.key == other.key
        else:
            raise NotImplemented

    def __ne__(self, other):
        if type(other) is not type(self):
            return True
        else:
            return self.key != other.key

    @property
    def key(self):
        if self._key is None:
            self._key = self._cmp_key()

        return self._key

    def _cmp_key(self):
        return ''

    def compare_str(self, other):
        return ['>>> diff in %s' % str(self)] + \
            self.run_ndiff(self.key, other.key)

    @property
    def otype(self):
        return self._out['output_type']

    def __str__(self):
        return '%s.%s' % (self.otype, self.name)

    @staticmethod
    def sanitize(s):
        """sanitize a string for comparison.

        fix universal newlines, strip trailing newlines, and normalize likely
        random values (memory addresses and UUIDs)

        Parameters
        ----------
        s : str
            string to be sanitized, i.e. remove UUIDs, Hex-addresses, unnecessary newlines
        """
        if not isinstance(s, basestring):
            return s
        # normalize newline:
        s = s.replace('\r\n', '\n')

        # ignore trailing newlines (but not space)
        s = s.rstrip('\n')

        # normalize hex addresses:
        s = re.sub(r'0x[a-f0-9]+', '0xFFFFFFFF', s)

        # normalize UUIDs:
        s = re.sub(r'[a-f0-9]{8}(\-[a-f0-9]{4}){3}\-[a-f0-9]{12}', 'U-U-I-D', s)

        return s

    @staticmethod
    def run_ndiff(original, testing):
        return list(difflib.ndiff(original.splitlines(1), testing.splitlines(1)))


class StdOutOutput(TypedOutput):
    name = 'stdout'
    output_type = 'stream'

    def __nonzero__(self):
        return super(StdOutOutput, self).__nonzero__() and \
            self._out['name'] == self.name

    def _cmp_key(self):
        return self.sanitize(self.text)

    @property
    def text(self):
        return str(self._out['text'])


class StdErrOutput(StdOutOutput):
    name = 'stderr'


class MimeBundleOutput(TypedOutput):
    name = 'mime'
    output_type = 'display_data'

    @property
    def data(self):
        return self._out['data']

    def __nonzero__(self):
        return super(MimeBundleOutput, self).__nonzero__() and \
            self.name in self.data

    def _cmp_key(self):
        return str(self.data[self.name])


class ImageOutput(MimeBundleOutput):
    def compare_str(self, other):
        return ['>>> diff in %s' % str(self)] + \
               ['size new : %d vs size old : %d )' % (len(self.key), len(other.key))]


class PNGOutput(ImageOutput):
    name = 'image/png'


class PNGOutputExecuted(PNGOutput):
    output_type = 'execute_result'


class SVGOutput(ImageOutput):
    name = 'image/svg'


class SVGOutputExecuted(PNGOutput):
    output_type = 'execute_result'


class TextPlainOutput(MimeBundleOutput):
    name = 'text/plain'

    @property
    def text(self):
        return str(self.data[self.name])

    def _cmp_key(self):
        return self.sanitize(self.text)


class TextPlainOutputExecuted(TextPlainOutput):
    output_type = 'execute_result'


# list all possible Mime / Output Types
registered_output_types = {
    tt.output_type + '.' + tt.name: tt for tt in [
        StdOutOutput, StdErrOutput, TextPlainOutput, TextPlainOutputExecuted,
        PNGOutput, PNGOutputExecuted, SVGOutput, SVGOutputExecuted
    ]}

# these types will be considered by default
used_output_types = ['stream.stdout', 'execute_result.text/plain']


def get_outs(cell_outputs, output_types):
    outs = []
    for output in cell_outputs:
        for tt_class in output_types:
            tt = registered_output_types[tt_class](output)
            if tt:
                outs.append(tt)

    return outs


# ==============================================================================
#  MAIN
# ==============================================================================

if __name__ == '__main__':
    total_start_time = time.time()
    parser = argparse.ArgumentParser(
        description='Run all cells in an ipython notebook as a test and ' +
                    'check whether these successfully execute and ' +
                    'compares their output to the one inside the notebook')

    parser.add_argument(
        'file',
        metavar='file.ipynb',
        help='the notebook to be checked',
        type=str)

    parser.add_argument(
        '-t', '--timeout', dest='timeout',
        type=int, default=300,
        help='the default timeout time in seconds for a cell ' +
             'evaluation. Default is 300s (5mins). Note that travis ' +
             'will consider it an error by default if after 600s (10mins) ' +
             'no output is generated. So 600s is the default limit by travis. '
             'However, a test cell that takes this long should be split in ' +
             'more than one or simplified.')

    parser.add_argument(
        '--rerun-if-timeout', dest='rerun',
        type=int, default=2, nargs='?',
        help='if set then a timeout in a cell will cause to run ' +
             'the. Default is 2 (means make up to 3 attempts)')

    parser.add_argument(
        '--restart-if-fail', dest='restart',
        type=int, default=0, nargs='?',
        help='if set then a fail in a cell will cause to restart ' +
             'the full notebook!. Default is 0 (means NO rerun).' +
             'Use this with care.')

    parser.add_argument(
        '-l', '--lazy', dest='lazy',
        action='store_true',
        default=False,
        help='if set to true then the default test is that cell ' +
             'have to match otherwise a diff will not be ' +
             'considered a failed test')

    parser.add_argument(
        '-s', '--strict', dest='strict',
        action='store_true',
        default=False,
        help='if set to true then the default test is that cell ' +
             'have to match otherwise a diff will not be ' +
             'considered a failed test')

    parser.add_argument(
        '--eval', dest='eval',
        type=str, default='', nargs='?',
        help='the argument will be run before the first cell is executed. ' +
             'This can be used to set specific values without changing the '
             'notebook.')

    parser.add_argument(
        '--tested-types', dest='ttypes',
        type=str, default='stream.stdout,execute_result.text/plain', nargs='?',
        help='the argument will specify be output types to be checked for'
             'equality. Currently the following types "' +
             ', '.join(registered_output_types.keys()) + ' " can be given as a'
             'comma `,` separated list. Default setting is "' +
             ', '.join(used_output_types) + '" which will test stdout and '
             'test/plain exeution results. No images will be tested.'
        )

    parser.add_argument(
        '--pass-if-timeout',
        dest='no_timeout', action='store_true',
        default=False,
        help='if set then a timeout (after last retry) is considered a ' +
             'passed test')

    parser.add_argument(
        '-d', '--show-diff',
        dest='show_diff',
        action='store_true',
        default=False,
        help='if set to true differences in the cell are shown ' +
             'in `diff` style')

    parser.add_argument(
        '--abort-if-fail',
        dest='abort_fail', action='store_true',
        default=False,
        help='if set to true then a fail will stop the whole test.')

    parser.add_argument(
        '--extra-arguments', dest='extra_arguments',
        type=str, default='', nargs='?',
        help='additional arguments passed to the ipython kernel on starting. '
             'Examples are `--pylab=inline`. ')

    parser.add_argument(
        '-y', '--pylab',
        dest='pylab', action='store_true',
        default=False,
        help='if set then pylab will be added to the extra arguments.')

    parser.add_argument(
        '-v', '--verbose',
        dest='verbose', action='store_true',
        default=False,
        help='if set then text output is send to the ' +
             'console.')

    args = parser.parse_args()
    ipynb = args.file
    verbose = args.verbose

    tv = IPyTestConsole()

    if args.strict:
        tv.default_results['diff'] = False

    if args.no_timeout:
        tv.default_results['timeout'] = True

    tv.fold_open('ipynb')
    tv.writeln('testing ipython notebook : "%s"' % ipynb)

    timeout_rerun = args.rerun
    fail_restart = args.restart

    extra_arguments = args.extra_arguments.split(";")

    if args.pylab:
        extra_arguments = ['--pylab=inline'] + extra_arguments

    used_output_types = [t_name.strip() for t_name in args.ttypes.split(',')]


    with open(ipynb) as f:
        nb = nbformat.reads(unicode(f.read()), 4)
        # Convert all notebooks to the format IPython 3.0.0 uses to
        # simplify comparison
        nb = nbformat.convert(nb, 4)

    notebook_restart = True
    notebook_run_count = 0

    while notebook_restart:
        notebook_restart = False
        notebook_run_count += 1

        tv.reset()
        tv.write("starting kernel ... ")
        with IPyKernel(extra_arguments=extra_arguments) as ipy:
            ipy.default_timeout = args.timeout
            tv.writeln("ok")

            nbs = ipynb.split('/')[-1].split('.')

            nb_class_name = nbs[1] + '.' + nbs[0].replace(" ", "_")

            tv.br()

            if hasattr(nb, 'worksheets'):
                ws = nb.worksheets[0]
            else:
                ws = nb

            if args.eval:
                ipy.execute(args.eval)

            for cell in ws.cells:
                if notebook_restart:
                    # if we restart anyway skip all remaining cells
                    continue

                if cell.cell_type == 'markdown':
                    for line in cell.source.splitlines():
                        # only tv.writeln(headlines in markdown
                        if line.startswith('#') and line[1] != '!':
                            tv.writeln(line)

                # if cell.cell_type == 'heading':
                #     tv.writeln('#' * cell.level + ' ' + cell.source)

                if cell.cell_type == 'raw':
                    # handle RAW cells
                    continue

                if cell.cell_type != 'code':
                    continue

                # if code cell then continue

                if ipy.is_empty_cell(cell):
                    # empty cell will not be tested
                    continue

                # if hasattr(cell, 'prompt_number'):
                #     tv.write(nb_class_name + '.' + 'In [%3i]' %
                #              cell.prompt_number + ' ... ')
                if hasattr(cell, 'execution_count') and \
                        cell.execution_count is not None:
                    tv.write(nb_class_name + '.' + 'In [%3i]' %
                             cell.execution_count + ' ... ')
                else:
                    tv.write(nb_class_name + '.' + 'In [---]' + ' ... ')

                nb_cell_commands = ipy.get_commands(cell)

                result = 'success'

                timeout = ipy.default_timeout

                if 'skip' in nb_cell_commands:
                    tv.write_result('skip')
                    continue

                cell_run_count = 0
                cell_run_again = True
                cell_passed = True

                ex_cell_outputs = []

                while cell_run_again:
                    cell_run_count += 1
                    cell_run_again = False
                    cell_passed = True

                    try:
                        if 'timeout' in nb_cell_commands:
                            ex_cell_outputs = ipy.run(
                                cell,
                                use_timeout=int(nb_cell_commands['timeout']))
                        else:
                            ex_cell_outputs = ipy.run(cell)

                    except Exception as e:
                        # we got a jupyter problem to execute something
                        # in the kernel at all. Not that the execution raised
                        # an error
                        # Might still be that the cell did not execute
                        # or timeout

                        if 'ignore' not in nb_cell_commands:
                            cell_passed = False
                            if repr(e) == 'Empty()':
                                # Assume it has been timed out!
                                if cell_run_count <= timeout_rerun:
                                    cell_run_again = True
                                    tv.write('timeout [retry #%d] ' % cell_run_count)
                                else:
                                    if 'pass-if-timeout' in nb_cell_commands:
                                        tv.write_result('timeout', okay_list={'timeout': True})
                                    elif 'fail-if-timeout' in nb_cell_commands:
                                        tv.write_result('timeout', okay_list={'timeout': False})
                                    else:
                                        tv.write_result('timeout')

                                        ipy.clear()

                            else:
                                tv.write_result('kernel')
                                tv.fold_open('ipynb.kernel')
                                tv.writeln('>>> ' + e[0] + ' ("' + e[1] + '")')
                                tv.writeln(repr(e[2]), indent=4)
                                tv.fold_close('ipynb.kernel')
                        else:
                            if repr(e) == 'Empty()':
                                # Assume it has been timed out!
                                tv.write('timeout / ')
                                tv.write_result('ignore')
                            else:
                                tv.write('kernel / ')
                                tv.write_result('ignore')
                                tv.fold_open('ipynb.kernel')
                                tv.writeln('>>> ' + e[0] + ' ("' + e[1] + '")')
                                tv.writeln(repr(e[2]), indent=4)
                                tv.fold_close('ipynb.kernel')

                if not cell_passed:
                    if tv.last_fail and notebook_run_count <= fail_restart:
                        notebook_restart = True

                    if args.abort_fail:
                        break
                    else:
                        continue

                failed = False
                diff = False
                diff_str = ''
                out_str = ''

                # Check first, if we have an error output

                for out in ex_cell_outputs:
                    if out.output_type == 'error':
                        # An python error occurred. Cell is not completed correctly
                        if 'ignore' not in nb_cell_commands:
                            tv.write_result('error')
                        else:
                            tv.write('error / ')
                            tv.write_result('ignore')

                        tv.fold_open('ipynb.error')
                        tv.writeln('>>> ' + out.ename + ' ("' + out.evalue + '")')

                        for idx, trace in enumerate(out.traceback[1:]):
                            tv.writeln(trace, indent=4)

                        tv.fold_close('ipynb.error')
                        failed = True

                # if there has been no `error` so far run the comparison

                # this will first filter cells we want to compare at all
                # and then run the comparison on these

                # we will create a sorted list of all relevant contenttypes

                ex_cell_outs = get_outs(ex_cell_outputs, used_output_types)
                nb_cell_outs = get_outs(cell.outputs, used_output_types)

                out_str = ''
                err_str = ''

                if verbose or 'verbose' in nb_cell_commands:
                    text_cells = get_outs(ex_cell_outputs, ['stream.stdout', 'execute_result.text/plain'])
                    for text_cell in text_cells:
                        out_str += text_cell.text.strip() + '\n'

                    text_cells = get_outs(ex_cell_outputs, ['stream.stderr'])
                    for text_cell in text_cells:
                        err_str += text_cell.text.strip() + '\n'

                if not failed:
                    if len(ex_cell_outs) != len(nb_cell_outs):
                        diff_str += tv.blue(">>> diff in number of relevant content parts %d vs %d\n") % (
                            len(ex_cell_outputs), len(cell.outputs))

                        if len(ex_cell_outs) > len(nb_cell_outs):
                            nb_cell_outs += ['---'] * (len(ex_cell_outs) - len(nb_cell_outs))
                        else:
                            ex_cell_outs += ['---'] * (len(nb_cell_outs) - len(ex_cell_outs))

                        for orig, test in zip(nb_cell_outs, ex_cell_outs):
                            diff_str += tv.green("    %36s ") % str(orig)
                            diff_str += ' | ' + tv.red("%s\n") % str(test)

                        diff = True
                    else:
                        for o1, o2 in zip(nb_cell_outs, ex_cell_outs):
                            if o1 != o2:
                                # Output is different
                                err_message = o2.compare_str(o1)
                                diff_str += tv.format_diff(err_message)
                                diff = True

                if diff and not failed:
                    if 'ignore' not in nb_cell_commands:
                        if 'strict' in nb_cell_commands:
                            # strict mode means a difference will fail the test
                            tv.write_result('diff', okay_list={'diff': False})
                        elif 'lazy' in nb_cell_commands:
                            # lazy mode means a difference will pass the test
                            tv.write_result('diff', okay_list={'diff': True})
                        else:
                            # use defaults
                            tv.write_result('diff')
                    else:
                        tv.write('diff / ')
                        tv.write_result('ignore')

                    if args.show_diff:
                        tv.fold_open('ipynb.diff')
                        tv.writeln(diff_str)
                        tv.fold_close('ipynb.diff')

                if not failed and not diff:
                    tv.write_result('success')

                if tv.last_fail and notebook_run_count <= fail_restart:
                    # we had a fail so restart the whole notebook
                    notebook_restart = True

                if out_str != '' and 'quiet' not in nb_cell_commands:
                    n_lines = len(out_str.strip().split('\n'))
                    tv.write(tv.blue(">>> stdout / result text [%d line(s)]\n" % n_lines))
                    tv.fold_open('ipynb.out')
                    tv.writeln(out_str, indent=4)
                    tv.fold_close('ipynb.out')

                if err_str != '' and 'quiet' not in nb_cell_commands:
                    n_lines = len(err_str.strip().split('\n'))
                    tv.write(tv.red(">>> stderr / result text [%d line(s)]\n" % n_lines))
                    tv.fold_open('ipynb.out')
                    tv.writeln(err_str, indent=4)
                    tv.fold_close('ipynb.out')

                if args.abort_fail and tv.last_fail:
                    # a fail should stop the tests (but allow retries)
                    tv.writeln(tv.blue('aborting tests!'))
                    break

            tv.br()
            total_run_time = time.time() - total_start_time
            tv.writeln("  testing results (%5.3f seconds)" % total_run_time)
            tv.writeln("  ================================")
            if tv.pass_count > 0:
                tv.writeln("    %3i cells passed [" %
                           tv.pass_count + tv.green('ok') + "]")
            if tv.fail_count > 0:
                tv.writeln("    %3i cells failed [" %
                           tv.fail_count + tv.red('fail') + "]")

            tv.br()
            tv.writeln("  %3i cells successfully replicated [success]" %
                       tv.result_count['success'])
            tv.writeln("  %3i cells had mismatched outputs [diff]" %
                       tv.result_count['diff'])
            tv.writeln("  %3i cells timed out during execution [time]" %
                       tv.result_count['timeout'])
            tv.writeln("  %3i cells ran with python errors [error]" %
                       tv.result_count['error'])
            tv.writeln("  %3i cells have been run without comparison [ignore]" %
                       tv.result_count['ignore'])
            tv.writeln("  %3i cells failed to even run (IPython error) [kernel]" %
                       tv.result_count['kernel'])
            tv.writeln("  %3i cells have been skipped [skip]" %
                       tv.result_count['skip'])

            if notebook_restart:
                tv.br()
                tv.writeln(
                    tv.red("  attempt #%d of max %d failed, restarting notebook!" % (
                        notebook_run_count, fail_restart + 1
                    ))
                )

            tv.br()
            tv.write("shutting down kernel ... ")

        tv.writeln('ok')

    tv.fold_close('ipynb')

    if tv.fail_count != 0:
        tv.writeln(tv.red('some tests not passed.'))
        exit(1)
    else:
        tv.writeln(tv.green('all tests passed.'))
        exit(0)
