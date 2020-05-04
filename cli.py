# Standard library modules.
import getopt
import logging
import os
import sys

# External dependencies.
import coloredlogs
from executor import validate_ionice_class
from executor.contexts import create_context
from executor.ssh.client import SecureTunnel
from humanfriendly.terminal import connected_to_terminal, usage, warning

# Modules included in our package.
from rsync_system_backup import RsyncSystemBackup
from rsync_system_backup.destinations import Destination, RSYNCD_PORT
from rsync_system_backup.exceptions import MissingBackupDiskError, RsyncSystemBackupError

# Public identifiers that require documentation.
__all__ = (
    'enable_explicit_action',
    'logger',
    'main',
)

# Initialize a logger.
logger = logging.getLogger(__name__)


def main():
    """Command line interface for the ``rsync-system-backup`` program."""
    # Initialize logging to the terminal and system log.
    coloredlogs.install(syslog=True)
    # Parse the command line arguments.
    context_opts = dict()
    program_opts = dict()
    dest_opts = dict()
    try:
        options, arguments = getopt.gnu_getopt(sys.argv[1:], 'bsrm:c:t:i:unx:fvqh', [
            'backup', 'snapshot', 'rotate', 'mount=', 'crypto=', 'tunnel=',
            'ionice=', 'no-sudo', 'dry-run', 'multi-fs', 'exclude=', 'force',
            'disable-notifications', 'verbose', 'quiet', 'help',
        ])
        for option, value in options:
            if option in ('-b', '--backup'):
                enable_explicit_action(program_opts, 'backup_enabled')
            elif option in ('-s', '--snapshot'):
                enable_explicit_action(program_opts, 'snapshot_enabled')
            elif option in ('-r', '--rotate'):
                enable_explicit_action(program_opts, 'rotate_enabled')
            elif option in ('-m', '--mount'):
                program_opts['mount_point'] = value
            elif option in ('-c', '--crypto'):
                program_opts['crypto_device'] = value
            elif option in ('-t', '--tunnel'):
                ssh_user, _, value = value.rpartition('@')
                ssh_alias, _, port_number = value.partition(':')
                tunnel_opts = dict(
                    ssh_alias=ssh_alias,
                    ssh_user=ssh_user,
                    # The port number of the rsync daemon.
                    remote_port=RSYNCD_PORT,
                )
                if port_number:
                    # The port number of the SSH server.
                    tunnel_opts['port'] = int(port_number)
                dest_opts['ssh_tunnel'] = SecureTunnel(**tunnel_opts)
            elif option in ('-i', '--ionice'):
                value = value.lower().strip()
                validate_ionice_class(value)
                program_opts['ionice'] = value
            elif option in ('-u', '--no-sudo'):
                program_opts['sudo_enabled'] = False
            elif option in ('-n', '--dry-run'):
                logger.info("Performing a dry run (because of %s option) ..", option)
                program_opts['dry_run'] = True
            elif option in ('-f', '--force'):
                program_opts['force'] = True
            elif option in ('-x', '--exclude'):
                program_opts.setdefault('exclude_list', [])
                program_opts['exclude_list'].append(value)
            elif option == '--multi-fs':
                program_opts['multi_fs'] = True
            elif option == '--disable-notifications':
                program_opts['notifications_enabled'] = False
            elif option in ('-v', '--verbose'):
                coloredlogs.increase_verbosity()
            elif option in ('-q', '--quiet'):
                coloredlogs.decrease_verbosity()
            elif option in ('-h', '--help'):
                usage(__doc__)
                return
            else:
                raise Exception("Unhandled option! (programming error)")
        if len(arguments) > 2:
            msg = "Expected one or two positional arguments! (got %i)"
            raise Exception(msg % len(arguments))
        if len(arguments) == 2:
            # Get the source from the first of two arguments.
            program_opts['source'] = arguments.pop(0)
        if arguments:
            # Get the destination from the second (or only) argument.
            dest_opts['expression'] = arguments[0]
            program_opts['destination'] = Destination(**dest_opts)
        elif not os.environ.get('RSYNC_MODULE_PATH'):
            # Show a usage message when no destination is given.
            usage(__doc__)
            return
    except Exception as e:
        warning("Error: %s", e)
        sys.exit(1)
    try:
        # Inject the source context into the program options.
        program_opts['source_context'] = create_context(**context_opts)
        # Initialize the program with the command line
        # options and execute the requested action(s).
        RsyncSystemBackup(**program_opts).execute()
    except Exception as e:
        if isinstance(e, RsyncSystemBackupError):
            # Special handling when the backup disk isn't available.
            if isinstance(e, MissingBackupDiskError):
                # Check if we're connected to a terminal to decide whether the
                # error should be propagated or silenced, the idea being that
                # rsync-system-backup should keep quiet when it's being run
                # from cron and the backup disk isn't available.
                if not connected_to_terminal():
                    logger.info("Skipping backup: %s", e)
                    sys.exit(0)
            # Known problems shouldn't produce
            # an intimidating traceback to users.
            logger.error("Aborting due to error: %s", e)
        else:
            # Unhandled exceptions do get a traceback,
            # because it may help fix programming errors.
            logger.exception("Aborting due to unhandled exception!")
        sys.exit(1)


def enable_explicit_action(options, explicit_action):
    """
    Explicitly enable an action and disable other implicit actions.
    :param options: A dictionary of options.
    :param explicit_action: The action to enable (one of the strings
                            'backup_enabled', 'snapshot_enabled',
                            'rotate_enabled').
    """
    options[explicit_action] = True
    for implicit_action in 'backup_enabled', 'snapshot_enabled', 'rotate_enabled':
        if implicit_action != explicit_action:
            options.setdefault(implicit_action, False)
