import React from 'react'

import TasksTabHead from '../presentational/TasksTabHead.jsx'
import TasksList from '../presentational/TasksList.jsx'


class TasksTab extends React.Component {
	constructor(props) {
		super(props);
	}

	render() {
		return (
			<div>
				<TasksTabHead />
				<TasksList tasks={this.props.tasks}/>
			</div>
		)
	}
}

export default TasksTab;