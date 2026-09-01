import { mount, parseConfig } from './embed'

mount(parseConfig(document.currentScript as HTMLScriptElement))
