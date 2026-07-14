import { constants as fsConstants, promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { isSea } from "node:sea";

export const ULTRACODE_TOOLS = Object.freeze([
    "ultracode_start",
    "ultracode_status",
    "ultracode_wait",
    "ultracode_cancel",
    "ultracode_resume",
    "ultracode_list",
]);

// task and search_code_subagent are the current runtime entry points that
// create agent sessions. The management tools cannot create agents, but hiding
// them prevents child sessions from discovering or steering unrelated work.
export const AGENT_CONTROL_TOOLS = Object.freeze([
    "task",
    "search_code_subagent",
    "read_agent",
    "write_agent",
    "list_agents",
]);

export const WORKSPACE_EXCLUDED_TOOLS = Object.freeze([
    ...ULTRACODE_TOOLS,
    ...AGENT_CONTROL_TOOLS,
]);

export const READ_ONLY_TOOLS = Object.freeze([
    "view",
    "grep",
    "glob",
    "web_fetch",
    "web_search",
]);

const ALL_TOOL_SOURCES = Object.freeze(["builtin:*", "mcp:*", "custom:*"]);

export function resolvePluginDataDir({
    extensionDir,
    pluginName = "costas-agent-plugin",
    env = process.env,
    home = os.homedir(),
}) {
    const injected = env.COPILOT_PLUGIN_DATA?.trim();
    if (injected) return path.resolve(injected);

    const pluginRoot = path.resolve(extensionDir, "..", "..");
    const marketplaceDir = path.dirname(pluginRoot);
    const installedPluginsDir = path.dirname(marketplaceDir);
    if (path.basename(installedPluginsDir) === "installed-plugins") {
        const copilotHome = path.dirname(installedPluginsDir);
        const marketplace = path.basename(marketplaceDir);
        const installedName = marketplace === "_direct" ? pluginName : path.basename(pluginRoot);
        return path.join(copilotHome, "plugin-data", marketplace, installedName);
    }

    const copilotHome = path.resolve(env.COPILOT_HOME?.trim() || path.join(home, ".copilot"));
    return path.join(copilotHome, "plugin-data", "_direct", pluginName);
}

function defaultSeaCheck() {
    try {
        return isSea();
    } catch {
        return false;
    }
}

async function requireUsableFile(candidate, label, platform, access, stat) {
    const resolved = path.resolve(candidate);
    let metadata;
    try {
        metadata = await stat(resolved);
        if (!metadata.isFile()) throw new Error("not a regular file");
        const mode =
            platform === "win32" || resolved.endsWith(".js")
                ? fsConstants.R_OK
                : fsConstants.X_OK;
        await access(resolved, mode);
    } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        throw new Error(`${label} is not a usable Copilot CLI file: ${resolved} (${reason})`);
    }
    return resolved;
}

/**
 * Resolve the executable and leading arguments consumed by SDK forStdio.
 *
 * The SDK appends --headless/--stdio itself. In a regular Node extension host,
 * process.execPath is Node, so the extracted CLI index.js must be the first
 * argument. In a SEA host, process.execPath is already the Copilot executable.
 */
export async function resolveCliLaunch({
    env = process.env,
    execPath = process.execPath,
    platform = process.platform,
    sea = defaultSeaCheck(),
    access = fs.access,
    stat = fs.stat,
} = {}) {
    const explicit = env.COPILOT_CLI_PATH?.trim();
    if (explicit) {
        return {
            path: await requireUsableFile(explicit, "COPILOT_CLI_PATH", platform, access, stat),
            args: [],
            source: "COPILOT_CLI_PATH",
        };
    }

    if (sea) {
        return {
            path: await requireUsableFile(execPath, "Copilot SEA executable", platform, access, stat),
            args: [],
            source: "sea",
        };
    }

    const distDir = env.COPILOT_CLI_DIST_DIR?.trim();
    if (!distDir) {
        throw new Error(
            "Regular Node extension hosts require COPILOT_CLI_DIST_DIR so Ultracode can launch the matching CLI index.js",
        );
    }

    const nodePath = await requireUsableFile(execPath, "Node executable", platform, access, stat);
    const cliEntry = await requireUsableFile(
        path.join(distDir, "index.js"),
        "COPILOT_CLI_DIST_DIR/index.js",
        platform,
        access,
        stat,
    );
    return {
        path: nodePath,
        args: [cliEntry],
        source: "node-dist",
    };
}

export function runtimeConnectionOptions(launch) {
    return {
        path: launch.path,
        ...(launch.args.length > 0 ? { args: [...launch.args] } : {}),
    };
}

export function childClientOptions({ connection, baseDirectory }) {
    return {
        connection,
        mode: "empty",
        baseDirectory,
        logLevel: "error",
        // The extension deliberately does not read or forward a token. The
        // spawned CLI can consume inherited GH_TOKEN or invoke `gh auth token`.
        useLoggedInUser: true,
    };
}

export function childToolPolicy(permissionMode) {
    if (permissionMode === "read-only") {
        return {
            availableTools: [...READ_ONLY_TOOLS],
            excludedTools: [...AGENT_CONTROL_TOOLS],
        };
    }
    return {
        availableTools: [...ALL_TOOL_SOURCES],
        excludedTools: [...WORKSPACE_EXCLUDED_TOOLS],
    };
}
