declare module 'react-cytoscapejs' {
  import type { Core, ElementDefinition, LayoutOptions, StylesheetCSS, StylesheetStyle } from 'cytoscape'
  import type { CSSProperties } from 'react'

  export interface CytoscapeComponentProps {
    elements: ElementDefinition[]
    style?: CSSProperties
    stylesheet?: (StylesheetStyle | StylesheetCSS)[]
    layout?: LayoutOptions
    cy?: (cy: Core) => void
  }

  export default function CytoscapeComponent(props: CytoscapeComponentProps): JSX.Element
}
