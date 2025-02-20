import paramiko
import time
import re
from typing import Optional

from netmiko.no_config import NoConfig
from netmiko.cisco_base_connection import CiscoSSHConnection


class FortinetSSH(NoConfig, CiscoSSHConnection):
    def _modify_connection_params(self) -> None:
        """Modify connection parameters prior to SSH connection."""
        paramiko_transport = getattr(paramiko, "Transport")
        paramiko_transport._preferred_kex = (
            "diffie-hellman-group14-sha1",
            "diffie-hellman-group-exchange-sha1",
            "diffie-hellman-group-exchange-sha256",
            "diffie-hellman-group1-sha1",
        )

    def session_preparation(self) -> None:
        """Prepare the session after the connection has been established."""
        delay_factor = self.select_delay_factor(delay_factor=0)
        output = ""

        # If "set post-login-banner enable" is set it will require you to press 'a'
        # to accept the banner before you login. This will accept if it occurs
        count = 1
        while count <= 30:
            output += self.read_channel()
            if "to accept" in output:
                self.write_channel("a\r")
                break
            else:
                time.sleep(0.33 * delay_factor)
            count += 1

        self._test_channel_read()
        self.set_base_prompt(alt_prompt_terminator="$")
        self.disable_paging()
        # Clear the read buffer
        time.sleep(0.3 * self.global_delay_factor)
        self.clear_buffer()

    def disable_paging(
        self,
        command: str = "terminal length 0",
        delay_factor: Optional[float] = None,
        cmd_verify: bool = True,
        pattern: Optional[str] = None,
    ) -> str:
        """Disable paging is only available with specific roles so it may fail."""
        check_command = "get system status | grep Virtual"
        output = self._send_command_timing_str(check_command)
        self.allow_disable_global = True
        self.vdoms = False
        self._output_mode = "more"

        if re.search(r"Virtual domain configuration: (multiple|enable)", output):
            self.vdoms = True
            vdom_additional_command = "config global"
            output = self._send_command_timing_str(
                vdom_additional_command, delay_factor=2
            )
            if "Command fail" in output:
                self.allow_disable_global = False
                if self.remote_conn is not None:
                    self.remote_conn.close()
                self.establish_connection(width=100, height=1000)

        new_output = ""
        if self.allow_disable_global:
            self._retrieve_output_mode()
            disable_paging_commands = [
                "config system console",
                "set output standard",
                "end",
            ]
            # There is an extra 'end' required if in multi-vdoms are enabled
            if self.vdoms:
                disable_paging_commands.append("end")
            outputlist = [
                self._send_command_timing_str(command, delay_factor=2)
                for command in disable_paging_commands
            ]
            # Should test output is valid
            new_output = self.RETURN.join(outputlist)

        return output + new_output

    def _retrieve_output_mode(self) -> None:
        """Save the state of the output mode so it can be reset at the end of the session."""
        reg_mode = re.compile(r"output\s+:\s+(?P<mode>.*)\s+\n")
        output = self._send_command_str("get system console")
        result_mode_re = reg_mode.search(output)
        if result_mode_re:
            result_mode = result_mode_re.group("mode").strip()
            if result_mode in ["more", "standard"]:
                self._output_mode = result_mode

    def cleanup(self, command: str = "exit") -> None:
        """Re-enable paging globally."""
        if self.allow_disable_global:
            # Return paging state
            output_mode_cmd = f"set output {self._output_mode}"
            enable_paging_commands = ["config system console", output_mode_cmd, "end"]
            if self.vdoms:
                enable_paging_commands.insert(0, "config global")
            # Should test output is valid
            for command in enable_paging_commands:
                self.send_command_timing(command)
        return super().cleanup(command=command)

    def save_config(
        self, cmd: str = "", confirm: bool = False, confirm_response: str = ""
    ) -> str:
        """Not Implemented"""
        raise NotImplementedError
