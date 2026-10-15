"""Explicit SSH transport. Credentials remain in a local file, never argv/logs."""
import argparse
import json
import os
from pathlib import Path
import shlex
import sys


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--host', required=True, help='Explicit user-owned SSH hostname')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--username', default='root')
    parser.add_argument('--accept-new-host-key', action='store_true', help='Explicit first-use trust for a human-supplied new endpoint; changed known keys still fail')
    parser.add_argument('--password-file', type=Path, required=True)
    parser.add_argument('--action', choices=('inspect', 'upload', 'download', 'run'), default='inspect')
    parser.add_argument('--local', type=Path)
    parser.add_argument('--remote')
    parser.add_argument('--command-file', type=Path)
    args = parser.parse_args()
    import paramiko
    root = args.root.resolve()
    work = root/'runtime/remote_monitor'
    work.mkdir(parents=True, exist_ok=True)
    client = paramiko.SSHClient()
    client.load_host_keys(str(work/'known_hosts'))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy() if args.accept_new_host_key else paramiko.RejectPolicy())
    try:
        secret = args.password_file.read_text(encoding='utf-8-sig').strip()
        if not secret:
            raise ValueError('Empty credential file')
        if not 1 <= args.port <= 65535 or not args.host or not args.username:
            raise ValueError('Invalid explicit SSH endpoint')
        client.connect(args.host, port=args.port, username=args.username, password=secret,
                       look_for_keys=False, allow_agent=False, timeout=20, auth_timeout=20, banner_timeout=20)
        del secret
        if args.action == 'inspect':
            interpreter = "for py in /root/miniconda3/bin/python /opt/conda/bin/python /usr/bin/python3 /usr/local/bin/python3; do if test -x \"$py\"; then exec \"$py\" -; fi; done; exec python3 -"
            stdin, stdout, stderr = client.exec_command(interpreter, timeout=120)
            stdin.write((root/'engine/scripts/inspect_remote.py').read_text(encoding='utf-8'))
            stdin.channel.shutdown_write()
            output = stdout.read().decode('utf-8')
            errors = stderr.read().decode('utf-8')
            code = stdout.channel.recv_exit_status()
            if code:
                save(work/'preflight_failure.json', {'status': 'remote_preflight_failed', 'returncode': code, 'stderr': errors})
                print(errors, file=sys.stderr)
                return 3
            result = json.loads(output)
            save(work/'server_preflight.json', result)
            save(work/'shutdown_record.json', result['shutdown'])
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.action in ('upload', 'download'):
            if not args.local or not args.remote or not args.remote.startswith('/root/autodl-tmp/harnessir_'):
                raise ValueError('Transfer requires local path and explicit HarnessIR remote destination')
            sftp = client.open_sftp()
            if args.action == 'upload':
                # No overwrite of arbitrary remote project/model files.
                directory = str(Path(args.remote).parent).replace('\\', '/')
                _, stdout, _ = client.exec_command('mkdir -p -- ' + shlex.quote(directory))
                if stdout.channel.recv_exit_status():
                    raise OSError('Could not create task directory')
                temporary = args.remote + '.uploading'
                sftp.put(str(args.local), temporary)
                sftp.posix_rename(temporary, args.remote)
            else:
                args.local.parent.mkdir(parents=True, exist_ok=True)
                temporary = args.local.with_suffix(args.local.suffix+'.downloading')
                sftp.get(args.remote, str(temporary))
                os.replace(temporary, args.local)
            print(json.dumps({'status':'transferred','action':args.action,'path':str(args.local)},ensure_ascii=False))
        else:
            if not args.command_file:
                raise ValueError('Explicit reviewed command file required')
            # Human/agent-authored deployment commands only. Never tool/model output.
            command = args.command_file.read_text(encoding='utf-8-sig')
            stdin, stdout, stderr = client.exec_command('bash -s', timeout=3600)
            stdin.write(command)
            stdin.channel.shutdown_write()
            for line in stdout:
                print(line, end='', flush=True)
            errors = stderr.read().decode('utf-8')
            if errors:
                print(errors, file=sys.stderr)
            return stdout.channel.recv_exit_status()
        return 0
    except paramiko.AuthenticationException:
        save(work/'connection_status.json', {'status':'authentication_failed','credentials_logged':False})
        print('SSH authentication failed; no credential contents recorded.', file=sys.stderr)
        return 4
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
