# Digi Router Configuration Training

![Digi Router Configuration Training dashboard](config_pages.png)

*Figure 1. The project dashboard is the starting page for the training
modules.*

## Purpose

This project is a self-paced, browser-based training guide for common Digi
router configuration tasks. It is intended to help technicians and learners
understand the main authentication, access-control, and logging options before
or while configuring a device.

The project is purely instructional: it does not connect to a router, send
configuration commands, store credentials, or change a device. Instead, it
presents focused, visual guides and configuration animations that explain where
each setting is located, what action to take, and what the setting is used for.

## What the site shows

The home page (`index.html`) is a dashboard that links to five training
modules. Each module is a standalone HTML page with a consistent Digi
TechSupport style and supporting screenshots or guided visual steps.

| Module | What it covers |
| --- | --- |
| Authentication | The fundamentals of validating user access on a Digi router. |
| User Groups | Creating groups and applying shared permissions and access levels. |
| RADIUS | Using a centralized RADIUS service for authentication, authorization, and accounting. |
| TACACS+ | Centralized administrative access, including more granular authorization controls. |
| Syslog | Forwarding router events to a remote syslog server for monitoring, troubleshooting, and auditing. |

Each module page contains an animated, step-by-step router configuration
walkthrough. The animation highlights the relevant area of the router interface
and progresses through the actions required for that topic. Learners can use
the controls to pause, resume, or move between steps while reviewing each
configuration action.

![Example of an animated configuration walkthrough](config_pages_steps.png)

*Figure 2. A module animation guides the learner through the router
configuration steps.*

These walkthroughs make the site useful as a quick reference during training
or as preparation before working on a live device.

## How to use it

No installation, server, or build process is required. All pages and assets are
stored locally in this directory.

1. Open `index.html` in a modern web browser.
2. Select one of the five cards on the dashboard.
3. Read the module instructions and follow the animated visual guidance for
   the chosen configuration topic.
4. Use the **Pause/Resume**, previous, and next controls to review an
   animation at your own pace.
5. Return to the dashboard and continue with another module as needed.

For the best learning flow, start with **Authentication**, then review **User
Groups**, and finally choose the centralized-access or logging topic that
matches the environment: **RADIUS**, **TACACS+**, or **Syslog**.

> **Important:** The examples in this project are training material. Confirm
> addresses, shared secrets, user permissions, security policies, and device
> firmware-specific options before applying an equivalent configuration to a
> production router.

## Project contents

- `index.html` — training dashboard and navigation entry point.
- `Authentication.html`, `Groups.html`, `radius.html`, `TACACS.html`, and
  `Syslog.html` — individual training modules.
- `img/` — images used by the modules.
- `digitechsupport.png` and `digiicono.png` — branding assets.
- `dashboard.webp` — dashboard preview used by the repository README.

Because the project is static, it can be copied to another computer, opened
offline, or hosted by any simple web server without special runtime
dependencies.
