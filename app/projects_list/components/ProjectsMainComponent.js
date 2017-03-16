import { connect } from 'react-redux';

import ProjectsMain from '../presentational/ProjectsMain.jsx';


function mapStateToProps(state){
	console.log(state);
    return {
        projects: state.projects
    }
}

const ProjectsMainComponent = connect(
	mapStateToProps
)(ProjectsMain)

export default ProjectsMainComponent