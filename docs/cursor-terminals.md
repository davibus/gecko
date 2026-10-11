# Cursor terminal persistence

Cursor's base user settings and the existing `DCALL` profile enable native persistent terminal sessions, revival after a window closes, a 1,000-line restored scrollback limit, and restoration of all windows. These are global Cursor settings. `terminal.integrated.hideOnStartup` is `whenEmpty`: an empty terminal view stays hidden on startup, while restored sessions remain available. No global or Gecko workspace terminal profiles are configured by this setup.

Cursor associates terminal sessions with the workspace opened in its window. Open Gecko Main, Space Force, and Action Tax Refund as distinct folders or `.code-workspace` files to keep their terminal collections separate. Each workspace can have its own terminal names and working directories. Opening a project through a different path or workspace file gives it a different workspace identity and may show a different terminal collection.

Keep custom terminal names already in use. If an idle terminal needs a name, use its tab's Rename action. Native persistence may restore that name and its working directory when the workspace is reopened; working-directory restoration depends on shell support. No fixed title or directory is imposed by this project. Do not rename or run commands in an active terminal solely to test persistence.

`.vscode/tasks.json` contains older optional PowerShell tasks, including `Open Gecko Terminals`. They have no folder-open trigger and are not part of terminal restoration. Do not run the composite task when sessions have restored: doing so would create additional terminals. No task in this project is configured to recreate a deleted terminal at startup.

On a later normal reopen, inspect the tabs within each workspace to see whether names, directories, and recent output returned. A reload can reconnect a process; after a full application restart Cursor may relaunch the shell rather than continue a command. Output restoration is limited to 1,000 lines, and PowerShell command history is separate from terminal scrollback. No process continues across a Windows restart or shutdown. If a terminal cannot be restored, recreate it manually with the desired name and directory; do not automatically run project scripts.

See the [VS Code persistent-session documentation](https://code.visualstudio.com/docs/terminal/advanced) for the underlying behavior. Runtime restoration still requires observation after a normal future reopen; this configuration does not require closing Cursor now.
