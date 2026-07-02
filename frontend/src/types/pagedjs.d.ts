declare module 'pagedjs' {
  export class Previewer {
    constructor(options?: Record<string, unknown>);
    preview(
      content: string | HTMLElement,
      stylesheets: Array<string | HTMLElement>,
      renderTo: HTMLElement
    ): Promise<{ total: number }>;
  }
}
